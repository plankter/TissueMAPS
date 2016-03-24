from sqlalchemy import Column, Integer, String, LargeBinary, Interval, ForeignKey
from sqlalchemy.dialects.postgres import JSONB
from sqlalchemy.orm import relationship

from tmlib.models import Model, DateMixIn


class Submission(Model, DateMixIn):

    '''A *submission* handles the processing of a computational *task*
    on a cluster.

    Attributes
    ----------
    task: gc3libs.Task
        submitted task
    experiment_id: int
        ID of the parent experiment
    experiment: tmlib.experiment.Experiment
        parent experiment to which the submission belongs
    user_id: int
        ID of the submitting user
    user: tmlib.user.User
        parent user to which the submission belongs
    '''

    #: Name of the corresponding database table
    __tablename__ = 'submissions'

    # Table columns
    experiment_id = Column(Integer, ForeignKey('experiments.id'))

    # Relationships to other tables
    experiment = relationship('Experiment', backref='submissions')

    def __init__(self, experiment_id):
        '''
        Parameters
        ----------
        experiment_id: int
            ID of the parent experiment
        '''
        self.experiment_id = experiment_id

    def __repr__(self):
        return (
            '<Submission(id=%r, experiment=%r)>'
            % (self.id, self.experiment.name)
        )


class Batch(Model):

    '''A *batch* describes all inputs as well as the expected outputs of
    an individual *task*.

    Attributes
    ----------
    name: str
        name of the corresponding task
    description: dict
        specification of inputs and outputs (and potentially other
        parameters)
    submission_id: int
        ID of the parent submission
    submission: tmlib.models.Submission
        parent submission to which the batch belongs
    '''

    #: Name of the corresponding database table
    __tablename__ = 'batches'

    # Table columns
    name = Column(String, index=True)
    description = Column(JSONB)
    submission_id = Column(Integer, ForeignKey('submissions.id'))

    # Relationships to other tables
    submission = relationship('Submission', backref='batches')

    def __init__(self, name, description, submission_id):
        '''
        Parameters
        ----------
        name: str
            name of the corresponding task
        description: dict
            specification of inputs and outputs (and potentially other
            parameters)
        submission_id: int
            ID of the parent submission

        See also
        --------
        :py:method:`tmlib.workflow.api.create_batches`
        '''
        self.name = name
        self.description = description
        self.submission_id = submission_id

    def __repr__(self):
        return (
            '<Batch(id=%r, name=%r, submission_id=%r)>'
            % (self.id, self.name, self.submission_id)
        )


class Task(Model):

    '''A *task* represents a computational job that can be submitted to a
    cluster for processing. Its state will be monitored while being processed.

    Attributes
    ----------
    name: str
        name of the job
    state: gc3libs.Run.State
        processing state of the task
    exitcode: int
        return value of the submitted program
    time: datetime.timedelta
        duration of the task
    memory: int
        memory used by the task in GB
    cpu_time: datetime.timedelta
        used cpu time of the task
    submission_id: int
        ID of the parent submission
    submission: tmlib.models.Submission
        parent submission to which the batch belongs
    '''

    #: Name of the corresponding database table
    __tablename__ = 'tasks'

    # Table columns
    state = Column(String, index=True)
    name = Column(String, index=True)
    exitcode = Column(Integer, index=True)
    time = Column(Interval)
    memory = Column(Integer)
    cpu_time = Column(Interval)
    data = Column(LargeBinary)
    submission_id = Column(Integer, ForeignKey('submissions.id'))

    # Relationships to other tables
    submission = relationship('Submission', backref='tasks')

    def __repr__(self):
        return (
            '<Task(id=%r, name=%r, submission_id=%r)>'
            % (self.id, self.name, self.submission_id)
        )
