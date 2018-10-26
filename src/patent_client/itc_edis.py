import json
import os
import re
import shutil
import time
import xml.etree.ElementTree as ET

import requests
from patent_client import CACHE_BASE
from patent_client import SETTINGS

from .util import Manager
from .util import Model
from .util import one_to_many
from .util import one_to_one

CLIENT_SETTINGS = SETTINGS["ItcEdis"]
if os.environ.get("EDIS_USER", False):
    USERNAME = os.environ["EDIS_USER"]
    PASSWORD = os.environ["EDIS_PASS"]
else:
    USERNAME = CLIENT_SETTINGS["Username"]
    PASSWORD = CLIENT_SETTINGS["Password"]

BASE_URL = "https://edis.usitc.gov/data"
CACHE_DIR = CACHE_BASE / "itc_edis"
CACHE_DIR.mkdir(exist_ok=True)

session = requests.Session()

# API Guide at: https://www.usitc.gov/docket_services/documents/EDIS3WebServiceGuide.pdf


class ITCInvestigationManager(Manager):
    max_retries = 3
    auth_time = 10 * 60  # Re-authenticate every # seconds
    last_auth = 0
    base_url = BASE_URL + "/investigation/"

    def authenticate():
        if (
            time.time() - ITCInvestigationManager.last_auth
            > ITCInvestigationManager.auth_time
        ):
            path = "/secretKey/" + USERNAME
            response = session.get(BASE_URL + path, params={"password": PASSWORD})
            tree = ET.fromstring(response.text)
            key = tree.find("secretKey").text
            session.auth = (USERNAME, key)

    def filter(self):
        raise NotImplementedError("EDIS Api does not have a search function!")

    def get(self, investigation_number):
        fname = CACHE_DIR / (investigation_number + ".json")
        if fname.exists():
            return ITCInvestigation(json.load(open(fname)))
        else:
            ITCInvestigationManager.authenticate()
            url = self.base_url + investigation_number
            response = session.get(url)
            tree = ET.fromstring(response.text)
            tree = tree[0][0]
            data = {
                "phase": tree.find("investigationPhase").text,
                "number": tree.find("investigationNumber").text,
                "status": tree.find("investigationStatus").text,
                "title": tree.find("investigationTitle").text,
                "type": tree.find("investigationType").text,
                "doc_list_url": tree.find("documentListUri").text,
                "docket_number": tree.find("docketNumber").text,
            }
            with open(fname, "w") as f:
                json.dump(data, f, indent=2)
            return ITCInvestigation(data)


class ITCInvestigation(Model):
    objects = ITCInvestigationManager()
    documents = one_to_many("patent_client.ITCDocument", investigation_number="number")

    def __repr__(self):
        return f"<ITCInvestigation(number={self.number})>"


class ITCDocumentsManager(Manager):
    primary_key = "investigation_number"
    base_url = BASE_URL + "/document"
    allowed_filters = {
        "investigation_number": "investigationNumber",
        "phase": "investigationPhase",
        "type": "documentType",
        "firm": "firmOrg",
        "security": "securityLevel",
    }

    def get(self, document_id):
        fname = CACHE_DIR / f"document-{document_id}.json"
        if not fname.exists():
            ITCInvestigationManager.authenticate()
            response = session.get(f"{self.base_url}/{document_id}")
            tree = ET.fromstring(response.text)
            doc_el = tree.find(".//document")
            data = self.parse_doc(doc_el)
            with open(fname, "w") as f:
                json.dump(data, f, indent=2)
        else:
            data = json.load(open(fname))
        return ITCDocument(data)

    def parse_doc(self, element):
        attribute_dict = dict(
            type="documentType",
            title="documentTitle",
            investigation_number="investigationNumber",
            security="securityLevel",
            filing_org="firmOrganization",
            filed_by="filedBy",
            filed_on_behalf_of="onBehalfOf",
            action_jacket_control_number="actionJacketControlNumber",
            memorandum_control_number="memorandumControlNumber",
            attachment_url="attachmentListUri",
            date="documentDate",
            last_modified="modifiedDate",
            id="id",
        )
        data = dict()
        for key, value in attribute_dict.items():
            data[key] = element.find(value).text.strip()
        return data

    def get_item(self, key):
        query = {self.allowed_filters[k]: v for (k, v) in self.filter_params.items()}
        page = int(key / 100) + 1
        location = key % 100
        query["pagenumber"] = page
        q_string = re.sub(r'[\{\}":, ]+', "-", json.dumps(query, sort_keys=True)[1:-1])
        fname = CACHE_DIR / f"document-page-{q_string}.json"
        if fname.exists():
            data = json.load(open(fname))
        else:
            ITCInvestigationManager.authenticate()
            response = session.get(self.base_url, params=query)
            tree = ET.fromstring(response.text)[0]
            data = list()
            for element in tree.findall("document"):
                data.append(self.parse_doc(element))
            with open(fname, "w") as f:
                json.dump(data, f, indent=2)
        return ITCDocument(data[location])


class ITCDocument(Model):
    objects = ITCDocumentsManager()
    investigation = one_to_one(
        "patent_client.ITCInvestigation", investigation_number="investigation_number"
    )
    attachments = one_to_many("patent_client.ITCAttachment", document_id="id")

    def __repr__(self):
        return f"<ITCDocument(title={self.title})>"


class ITCAttachmentManager(Manager):
    primary_key = "investigation_number"
    base_url = BASE_URL + "/attachment/"
    allowed_filters = ["document_id"]

    def get_item(self, key):
        doc_id = self.filter_params["document_id"]
        fname = CACHE_DIR / f"attachments-{doc_id}.json"
        if fname.exists() and False:
            data = json.load(open(fname))
        else:
            ITCInvestigationManager.authenticate()
            response = session.get(self.base_url + doc_id)
            tree = ET.fromstring(response.text)
            attribute_dict = dict(
                id="id",
                document_id="documentId",
                title="title",
                size="fileSize",
                file_name="originalFileName",
                pages="pageCount",
                created_date="createDate",
                last_modified_date="lastModifiedDate",
                download_url="downloadUri",
            )
            data = list()
            for element in tree.findall(".//attachment"):
                row = dict()
                for k, value in attribute_dict.items():
                    row[k] = element.find(value).text.strip()
                data.append(row)
            with open(fname, "w") as f:
                json.dump(data, f, indent=2)
        return ITCAttachment(data[key])


class ITCAttachment(Model):
    objects = ITCAttachmentManager()
    document = one_to_one("patent_client.ITCDocument", document_id="document_id")

    def __repr__(self):
        return f"<ITCAttachment(title={self.title})>"

    def download(self, path="."):
        *_, ext = self.file_name.split(".")
        filename = f"{self.document.title.strip()} - {self.title}.{ext}"
        cdir = os.path.join(CACHE_DIR, self.document.investigation.number)
        os.makedirs(cdir, exist_ok=True)
        cname = os.path.join(cdir, filename)
        oname = os.path.join(path, filename)
        if not os.path.exists(cname):
            response = session.get(self.download_url, stream=True)
            with open(cname, "wb") as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
        shutil.copy(cname, oname)


"""


    def get_all(self):
        more = True
        page = 1
        inv_list = list()
        while more:
            url = BASE_URL + '/investigation'
            params = {'pageNumber': page, 'investigationType': 'Sec 337'}
            response = requests.get(url, params=params, auth=self.auth)
            tree = ET.fromstring(response.text)
            investigations = tree[0]
            inv_list += [Investigation(tree=inv_tree, auth=self.auth) for inv_tree in investigations]
            if len(investigations) < 100:
                more = False
            else:
                page += 1
        return inv_list



class Investigation:
    def __init__(self, number=None, auth=None, tree=None):
        self.auth = auth
        if tree:
            self.process_tree(tree)
        else:
            self.number = str(number)
            self.edis_data()

    def edis_data(self):
        url = BASE_URL + '/investigation/' + self.number
        response = requests.get(url, auth=self.auth)
        tree = ET.fromstring(response.text)
        investigation = tree[0][0]
        self.process_tree(investigation)


    def process_tree(self, tree):


    @property
    def dict(self):
        return {
        'number': self.number,
        'title': self.title,
        'phase': self.phase,
        'status': self.status,
        'type': self.type,
        'docket_number': self.docket_number,
    }

class DocumentList:
    def __init__(self, url, auth):
        self.url = url
        self.auth = auth
        self.documents = list()
        self.pages = 1

    def fetch(self, key=1):
        desired_pages = int(key/100) + 1
        current_pages = self.pages
        for page in range(current_pages, desired_pages + 1):
            params = {'pagenumber': page}
            response = requests.get(self.url, auth=self.auth, params=params)
            print(response.text)
            tree = ET.fromstring(response.text)[0]
            for element in tree.findall('document'):
                doc = Document(element, self.auth)
                self.documents.append(doc)
        self.pages = desired_pages
        #xml = minidom.parseString(response.text)
        #print(xml.toprettyxml())

    def __getitem__(self, key):
        if not self.documents:
            self.fetch()
        return self.documents[key]

    def __setitem__(self, key, value):
        if not self.documents:
            self.fetch()
        if len(self.documents) < key - 1:
            self.fetch(key)
        self.documents[key] = value

    def __delitem__(self, key):
        if not self.documents:
            self.fetch()
        del self.documents[key]


def parse_date(string):
    if not string:
        return None
    return datetime.strptime(string, '%Y/%m/%d %H:%M:%S')

class Document:
    def __init__(self, xml_element, auth):
        self._attachments = False
        self.auth = auth


        self.last_modified = parse_date(self.last_modified)
        self.date = parse_date(self.date)


    @property
    def dict(self):
        return {
        'type': self.type,
        'title': self.title,
        'security': self.security,
        'filing_org': self.filing_org,
        'filed_by': self.filed_by,
        'filed_on_behalf_of': self.filed_on_behalf_of,
        'action_jacket_control_number': self.action_jacket_control_number,
        'memorandum_control_number': self.memorandum_control_number,
        'attachment_url': self.attachment_url,
        'date': self.date,
        'last_modified': self.last_modified,
    }

    @property
    def attachments(self):
        if self._attachments:
            return self._attachments
        response = requests.get(self.attachment_url, auth=self.auth)
        self._attachments = list()
        tree = ET.fromstring(response.text)[0]
        for element in tree.findall('attachment'):
            doc = Attachment(element, self.auth)
            self._attachments.append(doc)
        return self._attachments

class Attachment:
    def __init__(self, xml_element, auth):
        self.auth = auth
        self.id = xml_element.find('id').text
        self.doc_id = xml_element.find('documentId').text
        self.title = xml_element.find('title').text
        self.size = xml_element.find('fileSize').text
        self.file_name = xml_element.find('originalFileName').text
        self.pages = xml_element.find('pageCount').text
        self.created = parse_date(xml_element.find('createDate').text)
        self.last_modified = parse_date(xml_element.find('lastModifiedDate').text)
        self.download_url = xml_element.find('downloadUri').text

    @property
    def dict(self):
        return {
        'id': self.id,
        'doc_id': self.doc_id,
        'title': self.title,
        'size': self.size,
        'file_name': self.file_name,
        'pages': self.pages,
        'created': self.created,
        'last_modified': self.last_modified,
        'download_url': self.download_url,
    }
"""
