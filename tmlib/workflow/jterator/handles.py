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
'''A `Handle` describes a key-value pair which is either passed as
an argument to a Jterator module function or is returned by the function. The
approach can be considered a form of metaprogramming, where the object extends
the code of the actual module function via its properties and methods.
This is used to assert the correct type of arguments and return values and
enables storing data generated by modules to make it accessible outside the
scope of the module or retrieving data from the store when required by modules.
The object's attributes are specified as a mapping in a
`handles` YAML module descriptor file.
'''
import re
import sys
import json
import numpy as np
import pandas as pd
import mahotas as mh
import cv2
import skimage
import logging
import collections
import skimage.draw
import shapely.geometry
from geoalchemy2.shape import to_shape
from abc import ABCMeta
from abc import abstractproperty
from abc import abstractmethod

from tmlib.utils import same_docstring_as
from tmlib.utils import assert_type
from tmlib.image_utils import find_border_objects
import jtlib.utils

logger = logging.getLogger(__name__)


class Handle(object):

    '''Abstract base class for a handle.'''

    __metaclass__ = ABCMeta

    @assert_type(name='basestring', help='basestring')
    def __init__(self, name, help):
        '''
        Parameters
        ----------
        name: str
            name of the item, which must either match a parameter of the module
            function in case the item represents an input argument or the key
            of a key-value pair of the function's return value
        help: str
            help message
        '''
        self.name = name
        self.help = help

    @property
    def type(self):
        '''str: handle type'''
        return self.__class__.__name__


class InputHandle(Handle):

    '''Abstract base class for a handle whose value is used as an argument for
    a module function.
    '''

    __metaclass__ = ABCMeta

    def __init__(self, name, value, help):
        '''
        Parameters
        ----------
        name: str
            name of the item, which must match a parameter of the module
            function
        value:
            the actual argument of the module function parameter
        help: str
            help message
        '''
        super(InputHandle, self).__init__(name, help)
        self.value = value

    def to_dict(self):
        '''Returns attributes "name", "type", "help" and "value" as
        key-value pairs.

        Return
        ------
        dict
        '''
        attrs = dict()
        attrs['name'] = self.name
        attrs['type'] = self.type
        attrs['help'] = self.help
        attrs['value'] = self.value
        return attrs


class OutputHandle(Handle):

    '''Abstract base class for a handle whose value is returned by a module
    function.
    '''

    __metaclass__ = ABCMeta

    @same_docstring_as(Handle.__init__)
    def __init__(self, name, help):
        super(OutputHandle, self).__init__(name, help)

    @abstractproperty
    def value(self):
        '''value returned by module function'''
        pass

    def to_dict(self):
        '''Returns attributes "name", "type" and "help" as key-value pairs.

        Return
        ------
        dict
        '''
        attrs = dict()
        attrs['name'] = self.name
        attrs['type'] = self.type
        attrs['help'] = self.help
        return attrs


class PipeHandle(Handle):

    '''Abstract base class for a handle whose value can be piped between
    modules, i.e. returned by one module function and potentially passed as
    argument to another.
    '''

    __metaclass__ = ABCMeta

    @assert_type(key='basestring')
    def __init__(self, name, key, help):
        '''
        Parameters
        ----------
        name: str
            name of the item, which must either match a parameter of the module
            function in case the item represents an input argument or the key
            of a key-value pair of the function's return value
        key: str
            unique and hashable identifier; it serves as
            lookup identifier to retrieve the actual value of the item
        help: str
            help message

        '''
        super(PipeHandle, self).__init__(name, help)
        self.key = key

    @abstractproperty
    def value(self):
        '''Data that's returned by module function and possibly passed
        to other module functions.
        '''
        pass

    def to_dict(self):
        '''Returns attributes "name", "type", "help" and "key" as key-value
        pairs.

        Return
        ------
        dict
        '''
        attrs = dict()
        attrs['name'] = self.name
        attrs['type'] = self.type
        attrs['help'] = self.help
        attrs['key'] = self.key
        return attrs


class Image(PipeHandle):

    '''Base class for an image handle.'''

    @same_docstring_as(PipeHandle.__init__)
    def __init__(self, name, key, help):
        super(Image, self).__init__(name, key, help)

    @property
    def value(self):
        '''numpy.ndarray: pixels/voxels array'''
        return self._value

    @value.setter
    def value(self, value):
        if not isinstance(value, np.ndarray):
            raise TypeError(
                'Returned value for "%s" must have type numpy.ndarray.'
                % self.name
            )
        self._value = value

    def iterplanes(self):
        '''Iterates over 2D pixel planes of the image for each combination of
        time point and z-level.

        Returns
        -------
        Tuple[Tuple[int], numpy.ndarray]
        '''
        array = self.value
        if array.ndim == 2:
            array = array[..., np.newaxis, np.newaxis]
        elif array.shape == 3:
            array = array[..., np.newaxis]
        for t in xrange(array.shape[-1]):
            for z in xrange(array[..., t].shape[-1]):
                yield ((t, z), array[:, :, z, t])


class IntensityImage(Image):

    '''Class for an intensity image handle, where image pixel values encode
    intensity.
    '''

    def __init__(self, name, key, help=''):
        '''
        Parameters
        ----------
        name: str
            name of the item, which must either match a parameter of the module
            function in case the item represents an input argument or the key
            of a key-value pair of the function's return value
        key: str
            unique and hashable identifier; it serves as
            lookup identifier to retrieve the actual value of the item
        help: str, optional
            help message (default: ``""``)
        '''
        super(Image, self).__init__(name, key, help)

    @property
    def value(self):
        '''
        Returns
        -------
        numpy.ndarray[Union[numpy.uint8, numpy.uint16]]: pixels/voxels array
        '''
        return self._value

    @value.setter
    def value(self, value):
        if not isinstance(value, np.ndarray):
            raise TypeError(
                'Returned value for "%s" must have type numpy.ndarray.'
                % self.name
            )
        if not(value.dtype == np.uint8 or value.dtype == np.uint16):
            raise TypeError(
                'Returned value for "%s" must have data type '
                'uint8 or uint16' % self.name
            )
        self._value = value

    def __str__(self):
        return '<IntensityImage(name=%r, key=%r)>' % (self.name, self.key)


class MaskImage(Image):

    '''Class for an image handle, where pixels of the image with zero values
    represent background and pixels with values greater than zero represent
    foreground.
    '''

    @same_docstring_as(Image.__init__)
    def __init__(self, name, key, help=''):
        super(MaskImage, self).__init__(name, key, help)

    @property
    def value(self):
        '''numpy.ndarray: pixels/voxels array'''
        return self._value

    @value.setter
    def value(self, value):
        if not isinstance(value, np.ndarray):
            raise TypeError(
                'Returned value for "%s" must have type numpy.ndarray.'
                % self.name
            )
        if not(value.dtype == np.int32 or value.dtype == np.bool):
            raise TypeError(
                'Returned value for "%s" must have data type int32 or bool.'
                % self.name
            )
        self._value = value


class LabelImage(MaskImage):

    '''Class for an image handle, where connected pixel components of the image
    are labeled such that each component has a unique positive integer
    label and background is zero.
    '''

    @same_docstring_as(Image.__init__)
    def __init__(self, name, key, help=''):
        super(LabelImage, self).__init__(name, key, help)

    @property
    def value(self):
        '''numpy.ndarray[numpy.int32]: pixels/voxels array'''
        return self._value

    @value.setter
    def value(self, value):
        if not isinstance(value, np.ndarray):
            raise TypeError(
                'Returned value for "%s" must have type numpy.ndarray.'
                % self.name
            )
        if not value.dtype == np.int32:
            raise TypeError(
                'Returned value for "%s" must have data type int32.'
                % self.name
            )
        self._value = value

    def __str__(self):
        return '<LabelImage(name=%r, key=%r)>' % (self.name, self.key)


class BinaryImage(MaskImage):

    '''Class for an image handle, where pixels of the image are
    either background (``False``) or foreground (``True``).
    '''

    @same_docstring_as(Image.__init__)
    def __init__(self, name, key, help=''):
        super(BinaryImage, self).__init__(name, key, help)

    @property
    def value(self):
        '''numpy.ndarray[numpy.bool]: pixels/voxels array'''
        return self._value

    @value.setter
    def value(self, value):
        if not isinstance(value, np.ndarray):
            raise TypeError(
                'Value of key "%s" must have type numpy.ndarray.' % self.name
            )
        if value.dtype != np.bool:
            raise TypeError(
                'Value of key "%s" must have data type bool.' % self.name
            )
        self._value = value

    def __str__(self):
        return '<BinaryImage(name=%r, key=%r)>' % (self.name, self.key)


class SegmentedObjects(LabelImage):

    '''Class for a segmented objects handle, which represents a special type of
    label image handle, where pixel values encode segmented objects that should
    ultimately be visualized by `TissueMAPS` and for which features can be
    extracted.
    '''

    @assert_type(key='basestring')
    def __init__(self, name, key, help=''):
        '''
        Parameters
        ----------
        name: str
            name of the item
        key: str
            name that should be assigned to the objects
        '''
        super(SegmentedObjects, self).__init__(name, key, help)
        self._features = collections.defaultdict(list)
        self._save = False
        self._represent_as_polygons = True

    @property
    def labels(self):
        '''List[int]: unique object identifier labels'''
        return np.unique(self.value[self.value > 0]).astype(int).tolist()

    def to_points(self, y_offset, x_offset):
        '''Creates a point representation of each segmented object.
        The coordinates of the points contours are relative to the global map,
        i.e. an offset is added to the image site specific coordinates.

        Parameters
        ----------
        y_offset: int
            global vertical offset that needs to be subtracted from
            *y*-coordinates (*y*-axis is inverted)
        x_offset: int
            global horizontal offset that needs to be added to x-coordinates

        Returns
        -------
        Generator[Tuple[int], shapely.geometry.polygon.Point]]
            point (centroid with global map *x*, *y* coordinates)
            for each identified object hashable
            by time point, z-plane and one-based, site-specific label
        '''
        logger.debug('calculate centroids for objects of type "%s"', self.key)
        points = dict()
        for (t, z), plane in self.iterplanes():
            for label in self.labels:
                logger.debug('calculate centroid for object #%d', label)
                y, x = np.where(plane == label)
                point = shapely.geometry.Point(
                    int(np.mean(x)) + x_offset,
                    -1 * (int(np.mean(y)) + y_offset),
                )
                yield ((t, z, label), point)

    def to_polygons(self, y_offset, x_offset):
        '''Creates a polygon representation for each segmented object.
        The coordinates of the polygon contours are relative to the global map,
        i.e. an offset is added to the image site specific coordinates.

        Parameters
        ----------
        y_offset: int
            global vertical offset that needs to be subtracted from
            *y*-coordinates (*y*-axis is inverted)
        x_offset: int
            global horizontal offset that needs to be added to *x*-coordinates

        Returns
        -------
        Generator[Tuple[int], shapely.geometry.polygon.Polygon]]
            contour (simplified polygon with global map *x*, *y* coordinates)
            for each identified object hashable
            by time point, z-plane and one-based, site-specific label
        '''
        logger.debug('calculate polygons for objects type "%s"', self.key)

        # Set border pixels to background to find complete contours of
        # objects at the border of the image
        polygons = dict()
        for (t, z), plane in self.iterplanes():
            bboxes = mh.labeled.bbox(plane)
            # We set border pixels to zero to get closed contours for
            # border objects. This may cause problems for very small objects
            # at the border, because they may get lost.
            # We recreate them later on (see below).
            plane[0, :] = 0
            plane[-1, :] = 0
            plane[:, 0] = 0
            plane[:, -1] = 0

            for label in self.labels:
                bbox = bboxes[label]
                obj_im = jtlib.utils.extract_bbox_image(plane, bbox, pad=1)
                logger.debug('find contour for object #%d', label)
                # We could do this for all objects at once, but doing it
                # for each object individually ensures that we get the
                # correct number of objects and that coordinates are in the
                # correct order, i.e. sorted according to their label.
                mask = obj_im == label
                # NOTE: OpenCV return x, y coordinates. That means that
                # for numpy indexing one would need to flip the axes.
                _, contours, hierarchy = cv2.findContours(
                    (mask).astype(np.uint8) * 255,
                    cv2.RETR_CCOMP,  # two-level  hierarchy (holes)
                    cv2.CHAIN_APPROX_SIMPLE  # TODO: how to add offset?
                )
                if len(contours) == 0:
                    logger.warn(
                        'no contours identified for object #%d', label
                    )
                    # This is most likely an object that does not extend
                    # beyond the line of border pixels.
                    # To ensure a correct number of objects we represent
                    # it by a small polygon.
                    coords = np.array(np.where(self.value == label)).T
                    y, x = np.mean(coords, axis=0).astype(int)
                    shell = np.array([
                        [x-1, x+1, x+1, x-1, x-1],
                        [y-1, y-1, y+1, y+1, y-1]
                    ]).T
                    holes = None
                elif len(contours) > 1:
                    # It may happens that more than one contour is
                    # identified per object, for example if the object
                    # has holes, i.e. enclosed background pixels.
                    logger.debug(
                        '%d contours identified for object #%d',
                        len(contours), label
                    )
                    holes = list()
                    for i in range(len(contours)):
                        child_idx = hierarchy[0][i][2]
                        parent_idx = hierarchy[0][i][3]
                        # There should only be two levels with one
                        # contour each.
                        # TODO: prevent creation of holes for objects
                        # that are not supposed to have holes.
                        if parent_idx >= 0:
                            shell = np.squeeze(contours[parent_idx])
                        elif child_idx >= 0:
                            holes.append(np.squeeze(contours[child_idx]))
                        else:
                            # Same hierarchy level. This shouldn't happen.
                            # Take only the largest one.
                            lengths = [len(c) for c in contours]
                            idx = lengths.index(np.max(lengths))
                            shell = np.squeeze(contours[idx])
                            break
                else:
                    shell = np.squeeze(contours[0])
                    holes = None

                if shell.ndim < 2 or shell.shape[0] < 3:
                    logger.warn('polygon doesn\'t have enough coordinates')
                    # In case the contour cannot be represented as a
                    # valid polygon we create a little square to not loose
                    # the object.
                    y, x = np.array(mask.shape) / 2
                    # Create a closed ring with coordinates sorted
                    # counter-clockwise
                    shell = np.array([
                        [x-1, x+1, x+1, x-1, x-1],
                        [y-1, y-1, y+1, y+1, y-1]
                    ]).T

                # Add offset required due to alignment and cropping and
                # invert the y-axis as required by Openlayers.
                add_y = y_offset + bbox[0] - 1
                add_x = x_offset + bbox[2] - 1
                shell[:, 0] = shell[:, 0] + add_x
                shell[:, 1] = -1 * (shell[:, 1] + add_y)
                if holes is not None:
                    for i in range(len(holes)):
                        holes[i][:, 0] = holes[i][:, 0] + add_x
                        holes[i][:, 1] = -1 * (holes[i][:, 1] + add_y)
                poly = shapely.geometry.Polygon(shell, holes)
                # poly = poly.simplify(tolerance=0, preserve_topology=True)
                if not poly.is_valid:
                    logger.warn(
                        'invalid polygon for object #%d - trying to fix it',
                        label
                    )
                    # In some cases there may be invalid intersections
                    # that can be fixed with the buffer trick.
                    poly = poly.buffer(0)
                    if not poly.is_valid:
                        raise ValueError(
                            'Polygon of object #%d is invalid.' % label
                        )
                    if isinstance(poly, shapely.geometry.MultiPolygon):
                        logger.warn(
                            'object #%d has multiple polygons - '
                            'take largest', label
                        )
                        # Repair may create multiple polygons.
                        # We take the largest and discard the smaller ones.
                        areas = [g.area for g in poly.geoms]
                        index = areas.index(np.max(areas))
                        poly = poly.geoms[index]
                yield ((t, z, int(label)), poly)

    def from_polygons(self, polygons, y_offset, x_offset, dimensions):
        '''Creates a label image representation of segmented objects based
        on global map coordinates of object contours.

        Parameters
        ----------
        polygons: Dict[Tuple[int], shapely.geometry.polygon.Polygon]]
            polygon for each segmented object hashable by
            time point, z-plane and site-specific label
        y_offset: int
            global vertical offset that needs to be subtracted from
            y-coordinates
        x_offset: int
            global horizontal offset that needs to be subtracted from
            x-coordinates
        dimensions: Tuple[int]
            *y*, *x* dimensions of the label image that should be created

        Returns
        -------
        numpy.ndarray[numpy.int32]
            label image
        '''
        array = np.zeros(dimensions, dtype=np.int32)
        for (t, z, label), poly in polygons.iteritems():
            poly = to_shape(poly)
            coordinates = np.array(poly.exterior.coords).astype(int)
            x, y = np.split(coordinates, 2, axis=1)
            x -= x_offset
            y -= y_offset
            y, x = skimage.draw.polygon(y, x)
            array[y, x, z, t] = label
        self.value = np.squeeze(array)
        return self.value

    @property
    def is_border(self):
        '''Dict[Tuple[int], pandas.Series[bool]]: ``True`` if object lies
        at the border of the image and ``False`` otherwise
        '''
        mapping = dict()
        for (t, z), plane in self.iterplanes():
            for label, is_border in find_border_objects(plane).iteritems():
                mapping[(t, z, label)] = bool(is_border)
        return mapping

    @property
    def save(self):
        '''bool: whether objects should be saved'''
        return self._save

    @save.setter
    def save(self, value):
        if not isinstance(value, bool):
            raise TypeError('Attribute "save" must have type bool.')
        self._save = value

    @property
    def represent_as_polygons(self):
        '''bool: whether objects should be represented as polygons'''
        return self._represent_as_polygons

    @represent_as_polygons.setter
    def represent_as_polygons(self, value):
        if not isinstance(value, bool):
            raise TypeError(
                'Attribute "represent_as_polygons" must have type bool.'
            )
        self._represent_as_polygons = value

    @property
    def measurements(self):
        '''List[pandas.DataFrame]: features extracted for
        segmented objects at each time point
        '''
        if self._features:
            feature_values = list()
            for t in sorted(self._features.keys()):
                feature_values.append(self._features[t])
            return [pd.concat(v, axis=1) for v in feature_values]
        else:
            return [pd.DataFrame()]

    def add_measurement(self, measurement):
        '''Adds an additional measurement.

        Parameters
        ----------
        measurement: tmlib.workflow.jterator.handles.Measurement
            measured features for each segmented object
        '''
        if not isinstance(measurement, Measurement):
            raise TypeError(
                'Argument "measurement" must have type '
                'tmlib.workflow.jterator.handles.Measurement.'
            )
        for t, val in enumerate(measurement.value):
            if len(val.index) < len(self.labels):
                logger.warn(
                    'missing values for "%s" at time point %d',
                    measurement.name, t
                )
                for label in self.labels:
                    if label not in val.index:
                        logger.warn(
                            'add NaN values for missing object #%d', label
                        )
                        val.loc[label, :] = np.NaN
                val.sort_index(inplace=True)
            elif len(val.index) > len(self.labels):
                if len(np.unique(val.index)) < len(val.index):
                    logger.warn(
                        'duplicate values for "%s" at time point %d',
                        measurement.name, t
                    )
                    logger.info('remove duplicates and keep first')
                    val = val[~val.index.duplicated(keep='first')]
                else:
                    logger.warn(
                        'too many values for "%s" at time point %d',
                        measurement.name, t
                    )
                    for i in val.index:
                        if i not in self.labels:
                            logger.warn('remove values for object #%d', i)
                            val.drop(i, inplace=True)
            if np.any(val.index.values != np.array(self.labels)):
                raise ValueError(
                    'Labels of objects for "%s" at time point %d do not match!'
                    % (measurement.name, t)
                )
            if len(np.unique(val.columns)) != len(val.columns):
                raise ValueError(
                    'Column names of "%s" at time point %d must be unique.'
                    % (measurement.name, t)
                )
            self._features[t].append(val)

    def __str__(self):
        return '<SegmentedObjects(name=%r, key=%r)>' % (self.name, self.key)


class Scalar(InputHandle):

    '''Abstract base class for a handle for a scalar input argument.'''

    __metaclass__ = ABCMeta

    @assert_type(value=['int', 'float', 'basestring', 'bool', 'types.NoneType'])
    def __init__(self, name, value, help='', options=[]):
        '''
        Parameters
        ----------
        name: str
            name of the item, which must match a parameter of the module
            function
        value: str or int or float or bool
            value of the item, i.e. the actual argument of the function
            parameter
        help: str, optional
            help message (default: ``""``)
        options: List[str or int or float or bool]
            possible values for `value`
        '''
        if options:
            if value is not None:
                if value not in options:
                    raise ValueError(
                        'Argument "value" can be either "%s"'
                        % '" or "'.join(options)
                    )
        super(Scalar, self).__init__(name, value, help)
        self.options = options


class Boolean(Scalar):

    '''Handle for a boolean input argument.'''

    @assert_type(value='bool')
    def __init__(self, name, value, help='', options=[True, False]):
        '''
        Parameters
        ----------
        name: str
            name of the item, which must match a parameter of the module
            function
        value: bool
            value of the item, i.e. the actual argument of the function
            parameter
        help: str, optional
            help message (default: ``""``)
        options: List[bool]
            possible values for `value`
        '''
        if not all([isinstance(o, bool) for o in options]):
            raise TypeError('Options for "Boolean" can only be boolean.')
        super(Boolean, self).__init__(name, value, help, options)

    def __str__(self):
        return '<Boolean(name=%r, value=%r)>' % (self.name, self.value)


class Numeric(Scalar):

    '''Handle for a numeric input argument.'''

    @assert_type(value=['int', 'float', 'types.NoneType'])
    def __init__(self, name, value, help='', options=[]):
        '''
        Parameters
        ----------
        name: str
            name of the item, which must match a parameter of the module
            function
        value: int or float
            value of the item, i.e. the actual argument of the function
            parameter
        help: str, optional
            help message (default: ``""``)
        options: List[int or float]
            possible values for `value`
        '''
        super(Numeric, self).__init__(name, value, help, options)

    def __str__(self):
        return '<Numeric(name=%r, value=%r)>' % (self.name, self.value)


class Character(Scalar):

    '''Handle for a character input argument.'''

    @assert_type(value=['basestring', 'types.NoneType'])
    def __init__(self, name, value, help='', options=[]):
        '''
        Parameters
        ----------
        name: str
            name of the item, which must match a parameter of the module
            function
        value: basestring
            value of the item, i.e. the actual argument of the function
            parameter
        help: str, optional
            help message (default: ``""``)
        options: List[basestring]
            possible values for `value`
        '''
        super(Character, self).__init__(name, value, help, options)

    def __str__(self):
        return '<Character(name=%r, value=%r)>' % (self.name, self.value)


class Sequence(InputHandle):

    '''Class for a sequence input argument handle.'''

    @assert_type(value='list')
    def __init__(self, name, value, help=''):
        '''
        Parameters
        ----------
        name: str
            name of the item, which must match a parameter of the module
            function
        mode: str
            mode of the item, which defines the way it can be handled by the
            program
        value: List[str or int or float]
            value of the item, i.e. the actual argument of the function
            parameter
        help: str, optional
            help message (default: ``""``)
        '''
        for v in value:
            if all([not isinstance(v, t) for t in {int, float, basestring}]):
                raise TypeError(
                    'Elements of argument "value" must have type '
                        'int, float, or basestring.')
        super(Sequence, self).__init__(name, value, help)

    def __str__(self):
        return '<Sequence(name=%r)>' % self.name


class Plot(InputHandle):

    '''Handle for a plot that indicates whether the module should
    generate a figure or rather run in headless mode.
    '''

    @assert_type(value='bool')
    def __init__(self, name, value=False, help='', options=[True, False]):
        '''
        Parameters
        ----------
        name: str
            name of the item, which must match a parameter of the module
            function
        value: bool, optional
            whether plotting should be activated (default: ``False``)
        help: str, optional
            help message (default: ``""``)
        options: List[bool]
            possible values for `value`
        '''
        if not all([isinstance(o, bool) for o in options]):
            raise TypeError('Options for "Plot" can only be boolean')
        super(Plot, self).__init__(name, value, help)

    def __str__(self):
        return (
            '<Plot(name=%r, active=%r)>' % (self.name, self.value)
        )


class Measurement(OutputHandle):

    '''Handle for a measurement whose value is a list of two-dimensional labeled
    arrays with *n* rows and *p* columns, where *n* is the number of segmented
    objects and *p* the number of features that were measured for the
    referenced segmented objects.
    '''

    _NAME_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')

    @assert_type(
        objects='basestring',
        objects_ref='basestring', channel_ref=['basestring', 'types.NoneType']
    )
    def __init__(self, name, objects, objects_ref, channel_ref=None, help=''):
        '''
        Parameters
        ----------
        name: str
            name of the item, which must match a parameter of the module
            function
        objects: str
            object type to which features should are assigned
        objects_ref: str
            reference to object type for which features were extracted
            (may be the same as `objects`)
        channel_ref: str, optional
            reference to channel from which features were extracted
            (default: ``None``)
        help: str, optional
            help message (default: ``""``)
        '''
        super(Measurement, self).__init__(name, help)
        self.objects = objects
        self.objects_ref = objects_ref
        self.channel_ref = channel_ref

    @property
    def value(self):
        '''List[pandas.DataFrame]: features extracted for
        segmented objects at each time point
        '''
        return self._value

    @value.setter
    def value(self, value):
        if not isinstance(value, list):
            raise TypeError(
                'Value of key "%s" must have type list.'
                % self.name
            )
        if not all([isinstance(v, pd.DataFrame) for v in value]):
            raise TypeError(
                'Elements of returned value of "%s" must have type '
                'pandas.DataFrame.' % self.name
            )
        for v in value:
            for name in v.columns:
                if not self._NAME_PATTERN.search(name):
                    raise ValueError(
                        'Feature name "%s" must only contain '
                        'alphanumerical characters or underscores or hyphens'
                        % name
                    )
        self._value = value

    def to_dict(self):
        '''Returns attributes "name", "type", "help", "objects", "objects_ref"
        and "channel_ref" as key-value pairs.

        Return
        ------
        dict
        '''
        attrs = dict()
        attrs['name'] = self.name
        attrs['objects'] = self.objects
        attrs['objects_ref'] = self.objects_ref
        attrs['channel_ref'] = self.channel_ref
        attrs['type'] = self.type
        attrs['help'] = self.help
        return attrs

    def __str__(self):
        return '<Measurement(name=%r, objects=%r)>' % (self.name, self.objects)


class Figure(OutputHandle):

    '''Handle for a figure whose value is a JSON string representing
    a figure created by a module, see
    `Plotly JSON schema <http://help.plot.ly/json-chart-schema/>`_.
    '''

    def __init__(self, name, help=''):
        '''
        Parameters
        ----------
        name: str
            name of the item, which must match a parameter of the module
            function
        key: str
            name that should be given to the objects
        help: str, optional
            help message (default: ``""``)
        '''
        super(Figure, self).__init__(name, help)

    @property
    def value(self):
        '''str: JSON representation of a figure'''
        return self._value

    @value.setter
    def value(self, value):
        if not isinstance(value, basestring):
            raise TypeError(
                'Value of key "%s" must have type basestring.' % self.name
            )
        if value:
            try:
                json.loads(value)
            except ValueError:
                raise ValueError(
                    'Figure "%s" is not valid JSON.' % self.name
                )
        else:
            # minimal valid JSON
            value = json.dumps(dict())
        self._value = str(value)

    def __str__(self):
        return '<Figure(name=%r)>' % self.name


def create_handle(type, **kwargs):
    '''Factory function to create an instance of an implementation of the
    :class:`tmlib.workflow.jterator.handles.Handle` abstract base class.

    Parameters
    ----------
    type: str
        type of the handle item; must match a name of one of the
        implemented classes in :mod:`tmlib.workflow.jterator.handles`
    **kwargs: dict
        keyword arguments that are passed to the constructor of the class

    Returns
    -------
    tmlib.jterator.handles.Handle

    Raises
    ------
    AttributeError
        when `type` is not a valid class name
    TypeError
        when an unexpected keyword is passed to the constructor of the class
    '''
    current_module = sys.modules[__name__]
    try:
        class_object = getattr(current_module, type)
    except AttributeError:
        raise AttributeError('"%s" is not a valid handles type.' % type)
    return class_object(**kwargs)
