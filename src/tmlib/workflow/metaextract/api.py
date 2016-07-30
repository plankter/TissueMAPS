import os
import re
import logging
# import subprocess
from tmlib.readers import JavaBridge, BFOmeXmlReader

import tmlib.models as tm
from tmlib.workflow import register_api
from tmlib.utils import notimplemented
from tmlib.utils import same_docstring_as
from tmlib.errors import MetadataError
from tmlib.workflow.api import ClusterRoutines

logger = logging.getLogger(__name__)


@register_api('metaextract')
class MetadataExtractor(ClusterRoutines):

    '''Class for extraction of metadata from microscopic image files.

    Extracted metadata is formatted according to the
    `Open Microscopy Environment (OME) schema <http://www.openmicroscopy.org/Schemas/Documentation/Generated/OME-2015-01/ome.html>`_.
    '''

    def __init__(self, experiment_id, verbosity, **kwargs):
        '''
        Parameters
        ----------
        experiment_id: int
            ID of the processed experiment
        verbosity: int
            logging level
        **kwargs: dict
            ignored keyword arguments
        '''
        super(MetadataExtractor, self).__init__(experiment_id, verbosity)

    @staticmethod
    def _get_ome_xml_filename(image_filename):
        return re.sub(
            r'(%s)$' % os.path.splitext(image_filename)[1],
            '.ome.xml', image_filename
        )

    def create_batches(self, args):
        '''Creates job descriptions for parallel computing.

        Parameters
        ----------
        args: tmlib.steps.metaextract.args.MetaextractArgs
            step-specific arguments

        Returns
        -------
        Dict[str, List[dict]]
            job descriptions
        '''
        job_descriptions = dict()
        job_descriptions['run'] = list()
        count = 0
        with tm.utils.ExperimentSession(self.experiment_id) as session:
            for acq in session.query(tm.Acquisition)
                n_files = session.query(tm.MicroscopeImageFile.id).\
                    filter_by(acquisition_id=acq.id).\
                    count()
                if n_files == 0:
                    raise ValueError(
                        'Acquisition "%s" of plate "%s" doesn\'t have any '
                        'microscope image files' % (acq.name, acq.plate.name)
                    )
                batches = self._create_batches(
                    acq.microscope_image_files, args.batch_size
                )

                for files in batches:
                    file_map = {f.id: f.location for f in files}
                    count += 1
                    job_descriptions['run'].append({
                        'id': count,
                        'inputs': {
                            'microscope_image_files': file_map.values()
                        },
                        'outputs': dict(),
                        'microscope_image_file_ids': file_map.keys()
                    })

        return job_descriptions

    @same_docstring_as(ClusterRoutines.delete_previous_job_output)
    def delete_previous_job_output(self):
        with tm.utils.ExperimentSession(self.experiment_id) as session:
            logger.debug(
                'set attribute "omexml" of instances of class '
                'tmlib.models.MicroscopeImageFile to None'
            )
            n_files = session.query(tm.MicroscopeImageFile.id).count()
            session.bulk_update_mappings(
                tm.MicroscopeImageFile,
                [{'omexml': None} for _ in xrange(n_files)]
            )
            # for f in session.query(tm.MicroscopeImageFile):
            #     f.omexml = None

    def run_job(self, batch):
        '''Extracts OMEXML from microscope image or metadata files.

        Parameters
        ----------
        batch: dict
            description of the *run* job

        Note
        ----
        The actual processing is delegated to the
       `showinf <http://www.openmicroscopy.org/site/support/bio-formats5.1/users/comlinetools/display.html>`_
        Bioformats command line tool.

        Raises
        ------
        subprocess.CalledProcessError
            when extraction failed
        '''
        with JavaBridge() as java:
            with tm.utils.ExperimentSession(self.experiment_id) as session:
                for fid in batch['microscope_image_file_ids']:
                    img_file = session.query(tm.MicroscopeImageFile).get(fid)
                    logger.info('process image "%s"' % img_file.name)
                    # # The "showinf" command line tool writes the extracted OMEXML
                    # # to standard output.
                    # command = [
                    #     'showinf', '-omexml-only', '-nopix', '-novalid',
                    #     '-no-upgrade', '-no-sas', img_file.location
                    # ]
                    # p = subprocess.Popen(
                    #     command,
                    #     stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    # )
                    # stdout, stderr = p.communicate()
                    # if p.returncode != 0 or not stdout:
                    #     raise MetadataError(
                    #         'Extraction of OMEXML failed! Error message:\n%s'
                    #         % stderr
                    #     )
                    # try:
                    #     # We only want the XML. This will remove potential
                    #     # warnings and other stuff we don't want.
                    #     omexml = re.search(
                    #         r'<(\w+).*</\1>', stdout, flags=re.DOTALL
                    #     ).group()
                    # except:
                    #     raise RegexError('OMEXML metadata could not be extracted.')
                    with BFOmeXmlReader(img_file.location) as reader:
                        omexml = reader.read()
                    img_file.omexml = unicode(omexml)

    @notimplemented
    def collect_job_output(self, batch):
        pass

