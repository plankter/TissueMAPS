# TmLibrary - TissueMAPS library for distibuted image analysis routines.
# Copyright (C) 2016  Markus D. Herrmann, University of Zurich and Robin Hafen
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
import os
import shutil
import random
import logging
import inspect
import sqlalchemy
import sqlalchemy.orm
import sqlalchemy.pool
import sqlalchemy.exc
from sqlalchemy_utils.functions import create_database
from sqlalchemy_utils.functions import drop_database
from sqlalchemy.event import listens_for

from tmlib.models.base import ExperimentModel, FileSystemModel
from tmlib.config import LibraryConfig

logger = logging.getLogger(__name__)

_DATABASE_URI = None

#: Dict[str, sqlalchemy.engine.base.Engine]: mapping of chached database
#: engine objects for reuse within the current Python process hashable by URL
DATABASE_ENGINES = {}


def get_db_uri():
    '''Gets the URI for database connections from the configuration.

    Returns
    -------
    str
        database URI
    '''
    # TODO: could be done more elegantly
    # http://docs.sqlalchemy.org/en/latest/core/pooling.html#using-a-custom-connection-function
    global _DATABASE_URI
    if _DATABASE_URI is None:
        cfg = LibraryConfig()
        _DATABASE_URI = cfg.db_uri_sqla
    return _DATABASE_URI


def set_db_uri(db_uri):
    '''Sets the database URI for the current Python process and all child
    processes.

    Parameters
    ----------
    db_uri: str
        database URI

    Returns
    -------
    str
        database URI
    '''
    global _DATABASE_URI
    _DATABASE_URI = db_uri
    return _DATABASE_URI


def create_db_engine(db_uri):
    '''Creates a database engine with only one connection.

    Parameters
    ----------
    db_uri: str
        database uri

    Returns
    -------
    sqlalchemy.engine.base.Engine
        created database engine

    Warning
    -------
    The engine gets cached in :attr:`tmlib.models.utils.DATABASE_ENGINES`
    and reused within the same Python process.
    '''
    if db_uri not in DATABASE_ENGINES:
        logger.debug('create database engine for process %d', os.getpid())
        DATABASE_ENGINES[db_uri] = sqlalchemy.create_engine(
            db_uri, poolclass=sqlalchemy.pool.QueuePool,
            pool_size=5, max_overflow=10,
            # PostgreSQL uses autocommit by default. SQLAlchemy
            # (or actually psycopg2) makes use of multi-statement transactions
            # using BEGIN and COMMIT/ROLLBACK. This may cause problems when sharding
            # tables with Citusdata, for example. We may want to  turn it off to
            # use the Postgres default mode:
            # https://gist.github.com/carljm/57bfb8616f11bceaf865
        )
    else:
        logger.debug('reuse cached database engine for process %d', os.getpid())
    return DATABASE_ENGINES[db_uri]



@listens_for(sqlalchemy.pool.Pool, 'connect')
def _on_pool_connect(dbapi_con, connection_record):
    logger.debug('create database connection: %d', dbapi_con.get_backend_pid())


@listens_for(sqlalchemy.pool.Pool, 'checkin')
def _on_pool_checkin(dbapi_con, connection_record):
    logger.debug(
        'database connection returned to pool: %d',
        dbapi_con.get_backend_pid()
    )


@listens_for(sqlalchemy.pool.Pool, 'checkout')
def _on_pool_checkout(dbapi_con, connection_record, connection_proxy):
    logger.debug(
        'database connection retrieved from pool: %d',
        dbapi_con.get_backend_pid()
    )


def create_db_session_factory(engine):
    '''Creates a factory for creating a scoped database session that will use
    :class:`tmlib.models.utils.Query` to query the database.

    Parameters
    ----------
    engine: sqlalchemy.engine.base.Engine

    Returns
    -------
    sqlalchemy.orm.session.Session
    '''
    return sqlalchemy.orm.scoped_session(
        sqlalchemy.orm.sessionmaker(bind=engine, query_cls=Query)
    )


def delete_location(path):
    '''Deletes a location on disk.

    Parameters
    ----------
    path: str
        absolute path to directory or file
    '''
    if os.path.exists(path):
        logger.debug('remove location: %s', path)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.isfile(path):
            os.remove(path)


def remove_location_upon_delete(cls):
    '''Decorator function for an database model class that
    automatically removes the `location` that represents an instance of the
    class on the filesystem once the corresponding row is deleted from the
    database table.

    Parameters
    ----------
    cls: tmlib.models.base.DeclarativeABCMeta
       implemenation of :class:`tmlib.models.base.FileSystemModel`

    Raises
    ------
    AttributeError
        when decorated class doesn't have a "location" attribute
    '''
    def after_delete_callback(mapper, connection, target):
        delete_location(target.location)

    if not hasattr(cls, 'location'):
        raise AttributeError(
            'Decorated class must have a "location" attribute'
        )
    sqlalchemy.event.listen(cls, 'after_delete', after_delete_callback)
    return cls


def exec_func_after_insert(func):
    '''Decorator function for a database model class that calls the
    decorated function after an `insert` event.

    Parameters
    ----------
    func: function

    Examples
    --------
    @exec_func_after_insert(lambda target: do_something())
    SomeClass(db.Model):

    '''
    def class_decorator(cls):
        def after_insert_callback(mapper, connection, target):
            func(mapper, connection, target)
        sqlalchemy.event.listen(cls, 'after_insert', after_insert_callback)
        return cls
    return class_decorator


class Query(sqlalchemy.orm.query.Query):

    '''A custom query class.'''

    def __init__(self, *args, **kwargs):
        super(Query, self).__init__(*args, **kwargs)

    def delete(self):
        '''Performs a bulk delete query.

        Returns
        -------
        int
            count of rows matched as returned by the database's "row count"
            feature

        Note
        ----
        Also removes locations of instances on the file system.
        '''
        instances = self.all()
        locations = [getattr(inst, 'location', None) for inst in instances]
        # For performance reasons delete all rows via raw SQL without updating
        # the session and then enforce the session to update afterwards.
        if instances:
            logger.debug(
                'delete %d instances of class %s from database',
                len(instances), instances[0].__class__.__name__
            )
            super(Query, self).delete(synchronize_session=False)
            self.session.expire_all()
        if locations:
            logger.debug('remove corresponding locations on disk')
            for loc in locations:
                if loc is not None:
                    delete_location(loc)


class SQLAlchemy_Session(object):

    '''A wrapper around an instance of
    :class:`sqlalchemy.orm.session.Session` that manages persistence of
    database model objects.
    '''

    def __init__(self, session):
        '''
        Parameters
        ----------
        session: sqlalchemy.orm.session.Session
            `SQLAlchemy` database session
        '''
        self._session = session

    def __getattr__(self, attr):
        if hasattr(self._session, attr):
            return getattr(self._session, attr)
        elif hasattr(self, attr):
            return getattr(self, attr)
        else:
            raise AttributeError(
                'Object "%s" doens\'t have an attribute "%s".'
                % (self.__class__.__name__, attr)
            )

    @property
    def engine(self):
        '''sqlalchemy.engine.Engine: engine for the database connection'''
        return self._session.get_bind()

    def get_or_create(self, model, **kwargs):
        '''Gets an instance of a model class if it already exists or
        creates it otherwise.

        Parameters
        ----------
        model: type
            an implementation of :class:`tmlib.models.base.MainModel` or
            :class:`tmlib.models.base.ExperimentModel`
        **kwargs: dict
            keyword arguments for the instance that can be passed to the
            constructor of `model` or to
            :meth:`sqlalchemy.orm.query.query.filter_by`

        Returns
        -------
        tmlib.models.model
            an instance of `model`

        Note
        ----
        Adds and commits created instance. The approach can be useful when
        different processes may try to insert an instance constructed with the
        same arguments, but only one instance should be inserted and the other
        processes should re-use the instance without creation a duplication.
        The approach relies on uniqueness constraints of the corresponding table
        to decide whether a new entry would be considred a duplication.
        '''
        try:
            instance = self.query(model).filter_by(**kwargs).one()
            logger.debug('found existing instance: %r', instance)
        except sqlalchemy.orm.exc.NoResultFound:
            # We have to protect against situations when several worker
            # nodes are trying to insert the same row simultaneously.
            try:
                instance = model(**kwargs)
                logger.debug('created new instance: %r', instance)
                self._session.add(instance)
                self._session.commit()
                logger.debug('added and committed new instance: %r', instance)
            except sqlalchemy.exc.IntegrityError as err:
                logger.error(
                    'creation of instance %r failed:\n%s', instance, str(err)
                )
                self._session.rollback()
                try:
                    instance = self.query(model).filter_by(**kwargs).one()
                    logger.debug('found existing instance: %r', instance)
                except:
                    raise
            except TypeError:
                raise TypeError(
                    'Wrong arugments for instantiation of model class "%s".'
                    % model.__name__
                )
            except:
                raise
        except:
            raise
        return instance

    def drop_and_recreate(self, model):
        '''Drops a database table and re-creates it. Also removes
        locations on disk for each row of the dropped table.

        Parameters
        ----------
        model: tmlib.models.MainModel or tmlib.models.ExperimentModel
            database model class

        Warning
        -------
        Disk locations are removed after the table is dropped. This can lead
        to inconsistencies between database and file system representation of
        `model` instances when the process is interrupted.
        '''
        table = model.__table__
        engine = self._session.get_bind()
        locations_to_remove = []
        if table.exists(engine):
            if issubclass(model, FileSystemModel):
                model_instances = self._session.query(model).all()
                locations_to_remove = [m.location for m in model_instances]
            logger.info('drop table "%s"', table.name)
            self._session.commit()  # circumvent locking
            table.drop(engine)
        logger.info('create table "%s"', table.name)
        table.create(engine)
        logger.info('remove "%s" locations on disk', model.__name__)
        for loc in locations_to_remove:
            logger.debug('remove "%s"', loc)
            delete_location(loc)

    def get_or_create_all(self, model, args):
        '''Gets a collection of instances of a model class if they already
        exist or create them otherwise.

        Parameters
        ----------
        model: type
            an implementation of the :class:`tmlib.models.ExperimentModel`
            or :class:`tmlib.models.base.MainModel` abstract base class
        args: List[dict]
            keyword arguments for each instance that can be passed to the
            constructor of `model` or to
            ::meth:`sqlalchemy.orm.query.Query.filter_by`

        Returns
        -------
        List[tmlib.models.Model]
            instances of `model`
        '''
        instances = list()
        for kwargs in args:
            instances.extend(
                self.query(model).filter_by(**kwargs).all()
            )
        if not instances:
            try:
                instances = list()
                for kwargs in args:
                    instances.append(model(**kwargs))
                self._session.add_all(instances)
                self._session.commit()
            except sqlalchemy.exc.IntegrityError:
                self._session.rollback()
                instances = list()
                for kwargs in args:
                    instances.extend(
                        self.query(model).filter_by(**kwargs).all()
                    )
            except:
                raise
        return instances


class _Session(object):

    '''Class that provides access to all methods and attributes of
    :class:`sqlalchemy.orm.session.Session` and additional
    custom methods implemented in
    :class:`tmlib.models.utils.SQLAlchemy_Session`.

    Note
    ----
    The engine is cached and reused in case of a reconnection within the same
    Python process.

    Warning
    -------
    This is *not* thread-safe!
    '''
    _session_factories = dict()

    def __init__(self, db_uri):
        self._db_uri = db_uri
        if self._db_uri not in self.__class__._session_factories:
            engine = create_db_engine(self._db_uri)
            self.__class__._session_factories[self._db_uri] = \
                create_db_session_factory(engine)

    @property
    def engine(self):
        '''sqlalchemy.engine: engine object for the currently used database'''
        return DATABASE_ENGINES[self._db_uri]

    def __enter__(self):
        session_factory = self.__class__._session_factories[self._db_uri]
        self._session = SQLAlchemy_Session(session_factory())
        return self._session

    def __exit__(self, except_type, except_value, except_trace):
        if except_value:
            self._session.rollback()
        else:
            # TODO: if experiment is deleted, also delete its database
            self._session.commit()
            sqlalchemy.event.listen(
                self._session_factories[self._db_uri],
                'after_bulk_delete', self._after_bulk_delete_callback
            )
        self._session.close()
        DATABASE_ENGINES[self._db_uri].dispose()

    def _after_bulk_delete_callback(self, delete_context):
        '''Deletes locations defined by instances of :class`tmlib.Model`
        after they have been deleted en bulk.

        Parameters
        ----------
        delete_context: sqlalchemy.orm.persistence.BulkDelete
        '''
        logger.debug(
            'deleted %d rows from table "%s"',
            delete_context.rowcount, delete_context.primary_table.name
        )


class MainSession(_Session):

    '''Session scopes for interaction with the main `TissueMAPS` database.
    All changes get automatically committed at the end of the interaction.
    In case of an error, a rollback is issued.

    Examples
    --------
    from tmlib.models.utils import MainSession
    from tmlib.models import ExperimentReference

    with MainSession() as session:
        print session.query(ExperimentReference).all()

    See also
    --------
    :class:`tmlib.models.base.MainModel`
    '''

    def __init__(self, db_uri=None):
        '''
        Parameters
        ----------
        db_uri: str, optional
            URI of the main `TissueMAPS` database; defaults to the value of
            the environment variable ``TMPAS_DB_URI`` (default: ``None``)
        '''
        if db_uri is None:
            db_uri = get_db_uri()
        super(MainSession, self).__init__(db_uri)
        # if not database_exists(db_uri):
        #     raise ValueError('Database does not exist: %s' % db_uri)
        try:
            engine = create_db_engine(self._db_uri)
            connection = engine.connect()
            connection.close()
        except sqlalchemy.exc.OperationalError:
            raise ValueError('Database does not exist: %s' % self._db_uri)



class ExperimentSession(_Session):

    '''Session scopes for interaction with an experiment-secific database.
    All changes get automatically committed at the end of the interaction.
    In case of an error, a rollback is issued.

    Examples
    --------
    from tmlib.models.utils import ExperimentSession
    from tmlib.models import Plate

    with ExperimentSession(experiment_id=1) as session:
        print session.query(Plate).all()

    See also
    --------
    :class:`tmlib.models.base.ExperimentModel`
    '''

    def __init__(self, experiment_id, db_uri=None):
        '''
        Parameters
        ----------
        experiment_id: int
            ID of the experiment that should be accessed
        db_uri: str, optional
            URI of the main `TissueMAPS` database; defaults to the value of
            the environment variable ``TMPAS_DB_URI`` (default: ``None``)
        '''
        if db_uri is None:
            db_uri = get_db_uri()
        self.experiment_id = experiment_id
        if self.experiment_id is not None:
            if not isinstance(self.experiment_id, int):
                raise TypeError('Argument "experiment_id" must have type int.')
            db_uri = '{main}_experiment_{id}'.format(
                main=db_uri, id=self.experiment_id
            )
        super(ExperimentSession, self).__init__(db_uri)
        try:
            connection = DATABASE_ENGINES[self._db_uri].connect()
            connection.close()
        except sqlalchemy.exc.OperationalError:
            logger.debug(
                'create database for experiment %d', self.experiment_id
            )
            create_database(self._db_uri)
            engine = DATABASE_ENGINES[self._db_uri]
            # TODO: create template with postgis extension already created
            logger.debug(
                'create postgis extension in database for experiment %d',
                self.experiment_id
            )
            engine.execute('CREATE EXTENSION postgis;')
            logger.debug(
                'create tables in database for experiment %d',
                self.experiment_id
            )
            ExperimentModel.metadata.create_all(engine)
            engine.execute(
                'ALTER TABLE channel_layer_tiles ALTER COLUMN pixels SET STORAGE MAIN;'
            )

    def __enter__(self):
        session_factory = self.__class__._session_factories[self._db_uri]
        self._session = SQLAlchemy_Session(session_factory())
        return self._session

