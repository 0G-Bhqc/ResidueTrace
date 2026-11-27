import hashlib
import json
import shutil
from pathlib import Path

import pytest

import residuetrace
from residuetrace import audit


class Bundle:
    def __init__(self, directory):
        shutil.copytree(Path(residuetrace.__file__).with_name('demo'), directory)
        self.dir = directory
        self.path = directory / 'manifest.json'
        self.manifest = json.loads(self.path.read_text(encoding='utf-8'))
        self.regions = self.manifest['regions']

    def save(self):
        self.path.write_text(json.dumps(self.manifest), encoding='utf-8')
        return self.path

    def run(self):
        return audit(self.save())

    def file(self, role):
        return self.dir / self.manifest[role]['path']

    def replace(self, role, text):
        data = text.encode('utf-8')
        self.file(role).write_bytes(data)
        self.manifest[role]['sha256'] = hashlib.sha256(data).hexdigest()


@pytest.fixture
def bundle(tmp_path):
    return Bundle(tmp_path / 'bundle')
