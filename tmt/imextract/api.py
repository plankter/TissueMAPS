import os
import numpy as np
from cached_property import cached_property
from .. import imageutils
from ..image_readers import BioformatsImageReader
from ..cluster import ClusterRoutine


class ImageExtractor(ClusterRoutine):

    '''
    Class for extraction of pixel arrays (planes) stored in image files using
    the Bio-Formats library via
    `python-bioformats <https://github.com/CellProfiler/python-bioformats>`_.
    The extracted arrays are written to PNG files. This is done to save disk
    space due to (lossless) file compression and for downstream compatibility,
    since not many libraries are able to read images from the original file
    formats (often extended TIFF formats).
    '''

    def __init__(self, experiment, prog_name, logging_level='critical'):
        '''
        Initialize an instance of class ImageExtractor.

        Parameters
        ----------
        experiment: Experiment
            cycle object that holds information about the content of the
            experiment directory
        prog_name: str
            name of the corresponding program (command line interface)
        logging_level: str, optional
            configuration of GC3Pie logger; either "debug", "info", "warning",
            "error" or "critical" (defaults to ``"critical"``)

        Note
        ----
        `output_dir` will be created if it doesn't exist.

        Raises
        ------
        OSError
            when `metadata_file` does not exist
        '''
        super(ImageExtractor, self).__init__(prog_name, logging_level)
        self.experiment = experiment
        self.prog_name = prog_name
        for cycle in self.cycles:
            if not os.path.exists(os.path.join(cycle.metadata_dir,
                                               cycle.image_metadata_file)):
                raise OSError('Metadata file does not exist. '
                              'Use the "metaconvert" package to create it.')

    def _create_output_dirs(self):
        for cycle in self.cycles:
            if not os.path.exists(cycle.image_dir):
                os.mkdir(cycle.image_dir)

    @property
    def log_dir(self):
        '''
        Returns
        -------
        str
            directory where log files should be stored

        Note
        ----
        The directory will be sibling to the output directory.
        '''
        self._log_dir = os.path.join(self.experiment.dir,
                                     'log_%s' % self.prog_name)
        return self._log_dir

    @cached_property
    def cycles(self):
        '''
        Returns
        -------
        List[Wellplate or Slide]
            cycle objects
        '''
        self._cycles = self.experiment.cycles
        return self._cycles

    def create_joblist(self, **kwargs):
        '''
        Create a list of information required for the creation and processing
        of individual jobs.

        Parameters
        ----------
        **kwargs: dict
            additional input arguments as key-value pairs:
            * "batch_size": number of images per job (*int*)
        '''
        joblist = list()
        count = 0
        for cycle in self.cycles:
            md_batches = self._create_batches(cycle.image_metadata,
                                              kwargs['batch_size'])
            for batch in md_batches:
                count += 1
                joblist.append({
                    'id': count,
                    'inputs': [os.path.join(cycle.image_upload_dir,
                                            md.original_filename)
                               for md in batch],
                    'outputs': [os.path.join(cycle.image_dir, md.name)
                                for md in batch],
                    'metadata': [md.serialize() for md in batch],
                    'cycle': cycle.name

                })
        return joblist

    def _build_command(self, batch):
        job_id = batch['id']
        command = ['imextract']
        command.append(self.experiment.dir)
        command.extend(['run', '--job', str(job_id)])
        return command

    def run_job(self, batch):
        '''
        For each channel, extract all corresponding planes, perform maximum
        intensity projection in case there are more than one plane per channel,
        and write each resulting 2D channel plane to a separate PNG file.

        Parameters
        ----------
        batch: dict
            joblist element, i.e. description of a single job
        '''
        with BioformatsImageReader() as reader:
            for i, md in enumerate(batch['metadata']):
                # Perform maximum intensity projection to reduce
                # dimensionality to 2D if there is more than 1 z-stack
                stack = np.empty((md['original_dimensions'][0],
                                  md['original_dimensions'][1],
                                  len(md['original_planes'])),
                                 dtype=md['original_dtype'])
                for z in md['original_planes']:
                    filename = batch['inputs'][i]
                    stack[:, :, z] = reader.read_subset(
                                        filename, plane=z,
                                        series=md['original_series'])
                img = np.max(stack, axis=2)
                # Write plane (2D single-channel image) to file
                filename = batch['outputs'][i]
                imageutils.save_image_png(img, filename)

    def collect_job_output(self, joblist, **kwargs):
        pass

    def apply_statistics(self, joblist, wells, sites, channels, output_dir,
                         **kwargs):
        pass
