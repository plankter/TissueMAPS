# TmLibrary - TissueMAPS library for distibuted image analysis routines.
# Copyright (C) 2016, 2018, 2019  University of Zurich
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
import logging
import numpy as np
from sqlalchemy import Column, String, Integer, Text, Boolean, ForeignKey
from sqlalchemy.orm import relationship, backref, Session
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import UniqueConstraint
from cached_property import cached_property

from tmlib.utils import assert_type
from tmlib.utils import notimplemented
from tmlib.image import ChannelImage
from tmlib.image import IllumstatsImage
from tmlib.image import IllumstatsContainer
from tmlib.metadata import ChannelImageMetadata
from tmlib.metadata import IllumstatsImageMetadata
from tmlib.readers import DatasetReader
from tmlib.readers import ImageReader
from tmlib.writers import DatasetWriter
from tmlib.writers import ImageWriter
from tmlib.models.base import FileModel, DateMixIn
from tmlib.models.status import FileUploadStatus
from tmlib.models.utils import remove_location_upon_delete
from tmlib.models.alignment import SiteShift

logger = logging.getLogger(__name__)


@remove_location_upon_delete
class MicroscopeImageFile(FileModel, DateMixIn):

    '''Image file that was generated by the microscope.
    The file format differs between microscope types and may be vendor specific.
    '''

    __tablename__ = 'microscope_image_files'

    __table_args__ = (UniqueConstraint('name', 'acquisition_id'), )

    #: str: name given by the microscope
    name = Column(String(256), index=True)

    #: str: OMEXML metadata
    omexml = Column(Text)

    #: str: upload status
    status = Column(String(20), index=True)

    #: int: ID of the parent acquisition
    acquisition_id = Column(
        Integer,
        ForeignKey('acquisitions.id', onupdate='CASCADE', ondelete='CASCADE'),
        index=True
    )

    #: tmlib.models.acquisition.Acquisition: parent acquisition
    acquisition = relationship(
        'Acquisition',
        backref=backref('microscope_image_files', cascade='all, delete-orphan')
    )

    def __init__(self, name, acquisition_id):
        '''
        Parameters
        ----------
        name: str
            name of the microscope image file
        acquisition_id: int
            ID of the parent
            :class:`Acquisition <tmlib.models.acquisition.Acquisition>`
        '''
        self.name = name
        self.acquisition_id = acquisition_id
        self.status = FileUploadStatus.WAITING

    @hybrid_property
    def location(self):
        '''str: location of the file'''
        if self._location is None:
            self._location = os.path.join(
                self.acquisition.microscope_images_location, self.name
            )
        return self._location

    @location.setter
    def location(self, path_to_files):
        self._location = path_to_files

    @notimplemented
    def get(self):
        pass

    @notimplemented
    def put(self, data):
        pass

    def to_dict(self):
        '''Returns attributes "id", "name" and "status" as key-value pairs.

        Returns
        -------
        dict
        '''
        return {
            'id': self.id,
            'name': self.name,
            'status': self.status
        }

    def __repr__(self):
        return '<MicroscopeImageFile(id=%r, name=%r)>' % (self.id, self.name)


@remove_location_upon_delete
class MicroscopeMetadataFile(FileModel, DateMixIn):

    '''Metadata file that was generated by the microscope.
    The file format differs between microscope types and may be vendor specific.
    '''

    __tablename__ = 'microscope_metadata_files'

    __table_args__ = (UniqueConstraint('name', 'acquisition_id'), )

    #: str: name given by the microscope
    name = Column(String(256), index=True)

    #: str: upload status
    status = Column(String(20), index=True)

    #: int: ID of the parent acquisition
    acquisition_id = Column(
        Integer,
        ForeignKey('acquisitions.id', onupdate='CASCADE', ondelete='CASCADE'),
        index=True
    )

    #: tmlib.models.acquisition.Acquisition: parent acquisition
    acquisition = relationship(
        'Acquisition',
        backref=backref(
            'microscope_metadata_files', cascade='all, delete-orphan'
        )
    )

    def __init__(self, name, acquisition_id):
        '''
        Parameters
        ----------
        name: str
            name of the file
        acquisition_id: int
            ID of the parent
            :class:`Acquisition <tmlib.models.acquisition.Acquisition>`
        '''
        self.name = name
        self.acquisition_id = acquisition_id
        self.status = FileUploadStatus.WAITING

    @hybrid_property
    def location(self):
        '''str: location of the file'''
        if self._location is None:
            self._location = os.path.join(
                self.acquisition.microscope_metadata_location, self.name
            )
        return self._location

    @location.setter
    def location(self, path_to_files):
        self._location = path_to_files

    @notimplemented
    def get(self):
        pass

    @notimplemented
    def put(self, data):
        pass

    def to_dict(self):
        '''Returns attributes "id", "name" and "status" as key-value pairs.

        Returns
        -------
        dict
        '''
        return {
            'id': self.id,
            'name': self.name,
            'status': self.status
        }

    def __repr__(self):
        return '<MicroscopeMetdataFile(id=%r, name=%r)>' % (self.id, self.name)


@remove_location_upon_delete
class ChannelImageFile(FileModel, DateMixIn):

    '''A *channel image file* holds a single 2D pixels plane that was extracted
    from a microscope image file. It represents a unique combination of
    time point, z-level, site, and channel.
    '''

    #: str: name of the corresponding database table
    __tablename__ = 'channel_image_files'

    __table_args__ = (
        UniqueConstraint(
            'tpoint', 'zplane',
            'site_id', 'cycle_id', 'channel_id', 'acquisition_id'
        ),
    )

    #: int: zero-based index in the time series
    tpoint = Column(Integer, index=True)

    #: int: zero-based index in the z-stack
    zplane = Column(Integer, index=True)

    # dict: link to microscope image files from which this file originated
    file_map = Column(JSONB)

    #: int: ID of the parent cycle
    cycle_id = Column(
        Integer,
        ForeignKey('cycles.id', onupdate='CASCADE', ondelete='CASCADE'),
        index=True
    )

    #: int: ID of the parent site
    site_id = Column(
        Integer,
        ForeignKey('sites.id', onupdate='CASCADE', ondelete='CASCADE'),
        index=True
    )

    #: int: ID of the parent channel
    channel_id = Column(
        Integer,
        ForeignKey('channels.id', onupdate='CASCADE', ondelete='CASCADE'),
        index=True
    )

    #: int: ID of the parent acquisition
    acquisition_id = Column(
        Integer,
        ForeignKey('acquisitions.id', onupdate='CASCADE', ondelete='CASCADE'),
        index=True
    )

    #: tmlib.models.cycle.Cycle: parent cycle
    cycle = relationship(
        'Cycle',
        backref=backref('channel_image_files', cascade='all, delete-orphan')
    )

    #: tmlib.models.site.Site: parent site
    site = relationship(
        'Site',
        backref=backref('channel_image_files', cascade='all, delete-orphan')
    )

    #: tmlib.models.channel.Channel: parent channel
    channel = relationship(
        'Channel',
        backref=backref('image_files', cascade='all, delete-orphan')
    )

    #: tmlib.models.channel.Channel: parent channel
    acquisition = relationship(
        'Acquisition',
        backref=backref('channel_image_files', cascade='all, delete-orphan')
    )

    #: Format string for filenames
    FILENAME_FORMAT = 'channel_image_file_{id}.h5'

    def __init__(self, tpoint, zplane, site_id, acquisition_id, channel_id,
            file_map, cycle_id=None):
        '''
        Parameters
        ----------
        tpoint: int
            zero-based time point index in the time series
        zplane: int
            zero-based z-level index in the 3D stack
        site_id: int
            ID of the parent :class:`Site <tmlib.models.site.Site>`
        channel_id: int
            ID of the parent :class:`Channel <tmlib.models.channel.Channel>`
        acquisition_id: int
            ID of the parent
            :class:`Acquisition <tmlib.models.acquisition.Acquisition>`
        file_map: Dict[str, list]
            mapping to link the file to each corresponding
            :class:`MicroscopeImageFile <tmlib.models.file.MicroscopeImageFile>`
            from which is was derived as well as the locations within the file
            (a channel image file might be linked to more than one microscope
            image file in case it was obtained by projection of a z-stack,
            for example)
        cycle_id: int, optional
            ID of the parent :class:`Cycle <tmlib.models.cycle.Cycle>`
        '''
        self.tpoint = tpoint
        self.zplane = zplane
        self.site_id = site_id
        self.cycle_id = cycle_id
        self.channel_id = channel_id
        self.acquisition_id = acquisition_id
        self.file_map = file_map

    def get(self):
        '''Gets stored image.

        Returns
        -------
        tmlib.image.ChannelImage
            image stored in the file
        '''
        metadata = ChannelImageMetadata(
            channel_id=self.channel_id,
            site_id=self.site_id,
            tpoint=self.tpoint,
            zplane=self.zplane,
            cycle_id=self.cycle_id
        )
        with DatasetReader(self.location) as f:
            array = f.read('array')
        metadata.bottom_residue = self.site.bottom_residue
        metadata.top_residue = self.site.top_residue
        metadata.left_residue = self.site.left_residue
        metadata.right_residue = self.site.right_residue

        session = Session.object_session(self)
        shifts = session.query(SiteShift.y, SiteShift.x).\
            filter_by(site_id=self.site_id, cycle_id=self.cycle_id).\
            one_or_none()
        if shifts is not None:
            metadata.x_shift = shifts.x
            metadata.y_shift = shifts.y
        return ChannelImage(array, metadata)

    @assert_type(image=ChannelImage)
    def put(self, image):
        '''Puts image to storage.

        Parameters
        ----------
        image: tmlib.image.ChannelImage
            pixels data that should be stored in the image file
        '''
        with DatasetWriter(self.location, truncate=True) as f:
            f.write('array', image.array, compression=True)

    @hybrid_property
    def location(self):
        '''str: location of the file'''
        if self._location is None:
            self._location = os.path.join(
                self.channel.get_image_file_location(self.id),
                self.FILENAME_FORMAT.format(id=self.id)
            )
        return self._location

    def __repr__(self):
        return '<%s(id=%r, tpoint=%r, zplane=%r, site_id=%r, channel_id=%r)>' % (
            self.__class__.__name__, self.id, self.tpoint, self.zplane,
            self.site_id, self.channel_id
        )


@remove_location_upon_delete
class IllumstatsFile(FileModel, DateMixIn):

    '''An *illumination statistics file* holds matrices for mean and standard
    deviation values calculated at each pixel position across all images of
    the same *channel* and *cycle*.

    '''

    #: Format string to build filename
    FILENAME_FORMAT = 'illumstats_file_{id}.h5'

    __tablename__ = 'illumstats_files'

    __table_args__ = (UniqueConstraint('channel_id'), )

    #: int: ID of parent channel
    channel_id = Column(
        Integer,
        ForeignKey('channels.id', onupdate='CASCADE', ondelete='CASCADE'),
        index=True
    )

    #: tmlib.models.channel.Channel: parent channel
    channel = relationship(
        'Channel',
        backref=backref('illumstats_files', cascade='all, delete-orphan')
    )

    def __init__(self, channel_id):
        '''
        Parameters
        ----------
        channel_id: int
            ID of the parent channel
        '''
        self.channel_id = channel_id

    def get(self):
        '''Get illumination statistics images from store.

        Returns
        -------
        Illumstats
            illumination statistics images
        '''
        logger.debug(
            'get data from illumination statistics file: %s', self.location
        )
        metadata = IllumstatsImageMetadata(channel_id=self.channel.id)
        with DatasetReader(self.location) as f:
            mean = IllumstatsImage(f.read('mean'), metadata)
            std = IllumstatsImage(f.read('std'), metadata)
            keys = f.read('percentiles/keys')
            values = f.read('percentiles/values')
            percentiles = dict(zip(keys, values))
        return IllumstatsContainer(mean, std, percentiles).smooth()

    @assert_type(data=IllumstatsContainer)
    def put(self, data):
        '''Put illumination statistics images to store.

        Parameters
        ----------
        data: IllumstatsContainer
            illumination statistics
        '''
        logger.debug(
            'put data to illumination statistics file: %s', self.location
        )
        with DatasetWriter(self.location, truncate=True) as f:
            f.write('mean', data.mean.array)
            f.write('std', data.std.array)
            f.write('/percentiles/keys', data.percentiles.keys())
            f.write('/percentiles/values', data.percentiles.values())

    @hybrid_property
    def location(self):
        '''str: location of the file'''
        if self._location is None:
            self._location = os.path.join(
                self.channel.illumstats_location,
                self.FILENAME_FORMAT.format(id=self.id)
            )
        return self._location

    def __repr__(self):
        return (
            '<IllumstatsFile(id=%r, channel_id=%r)>'
            % (self.id, self.channel_id)
        )
