from os.path import join, dirname, realpath
from tmt.utils import load_config
from tmt.visi.utils import check_visi_config

__version__ = '0.1.1'


logo = '''
      _    _ 
 __ _(_)__(_)   visi (%(version)s)
 \ V / (_-< |   Convert Visitron's .stk files to .png images
  \_/|_/__/_|   https://github.com/HackerMD/TissueMAPSToolbox

'''

# Create configuration dictionary that defines default parameters
config_filename = join(dirname(realpath(__file__)), 'visi.config')

config = load_config(config_filename)
check_visi_config(config)
