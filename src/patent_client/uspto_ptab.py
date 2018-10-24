import requests
import json
from copy import deepcopy
from patent_client import CACHE_BASE
from patent_client.util import Manager, hash_dict, one_to_one, one_to_many, Model
import inflection
import mimetypes
import os
import shutil
from dateutil.parser import parse as parse_dt

CACHE_DIR = CACHE_BASE / 'ptab'
CACHE_DIR.mkdir(exist_ok=True)

session = requests.Session()

class PtabManager(Manager):
    page_size = 25

    def __init__(self, *args, **kwargs):
        self.args = args 
        self.kwargs = kwargs
        self.obj_class = globals().get(self.obj_class)
    
    def get_item(self, key):
        offset = int(key / self.page_size) * self.page_size
        position = (key % self.page_size)
        data = self.request(dict(offset=offset))
        results = data['results']
        return self.obj_class(results[position])
    
    def __len__(self):
        response = self.request()
        response_data = response
        count = response_data['metadata']['count']
        return count
        
    def request(self, params=dict()):
        params = {**{self.primary_key: self.args}, **self.kwargs, **params}
        params = {inflection.camelize(k, uppercase_first_letter=False): v for (k, v) in params.items()}
        fname = CACHE_DIR / f'{self.__class__}-{hash_dict(params)}.json'
        if not fname.exists():
            response = session.get(self.base_url, params=params)
            with open(fname, 'w') as f:
                json.dump(response.json(), f, indent=True)
        return json.load(open(fname))
        
class PtabTrialManager(PtabManager):
    base_url = 'https://ptabdata.uspto.gov/ptab-api/trials'
    obj_class = 'PtabTrial'
    primary_key = 'trial_number'
    
class PtabDocumentManager(PtabManager):
    base_url = 'https://ptabdata.uspto.gov/ptab-api/documents'
    obj_class = 'PtabDocument'
    primary_key = 'id'

class PtabTrial(Model):
    objects = PtabTrialManager()
    us_application = one_to_one('patent_client.USApplication', appl_id='application_number')
    documents = one_to_many('patent_client.PtabDocument', trial_number='trial_number')

    def __repr__(self):
        return f'<PtabTrial(trial_number={self.trial_number})>'

class PtabDocument(Model):
    objects = PtabDocumentManager()
    trial = one_to_one('patent_client.PtabTrial', trial_number='trial_number')

    def download(self, path='.'):
        url = self.links[1]['href']
        extension = mimetypes.guess_extension(self.media_type)
        base_name = self.title.replace('/', '_') + extension
        cdir = os.path.join(CACHE_DIR, self.trial_number)
        os.makedirs(cdir, exist_ok=True)
        cname = os.path.join(cdir, base_name)
        oname = os.path.join(path, base_name)
        if not os.path.exists(cname):
            response = session.get(url, stream=True)
            with open(cname, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
        shutil.copy(cname, oname)

    def __repr__(self):
        return f'<PtabDocument(title={self.title})>'

