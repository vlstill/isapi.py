import requests
import requests.exceptions
import json
from isapi.iscommon import ISAPIException
from typing import Optional, Union, List


class FileAPIException(ISAPIException):
    pass


class APIKey:
    def __init__(self, raw_api_key: str) -> None:
        self.raw_api_key = raw_api_key


class FileMeta:
    def __init__(self, data: dict) -> None:
        self.dir = False
        self.ispath = data["cesta"]
        self.shortname = data["zkratka"]
        self.name = data.get("nazev")
        self.annotation = data.get("popis")
        self.read = bool(int(data.get("mam_precteno", "0")))
        self.mime: Optional[str] = None
        if "objekty" in data and len(data["objekty"]):
            obj = data["objekty"]["objekt"][0]
            self.ispath = obj["cesta"]
            if self.name is None:
                self.name = obj["jmeno_souboru"]
            self.shortname = obj["jmeno_souboru"]
            self.mime = obj["mime_type"]
            self.author = int(obj["vlozil_uco"])
        else:
            self.author = int(data["zmenil_uco"])


class DirMeta(FileMeta):
    def __init__(self, data: dict) -> None:
        FileMeta.__init__(self, data)
        self.dir = True
        self.entries: List[FileMeta] = []

    def _append(self, data: dict) -> None:
        if int(data["pocet_poduzlu"]) == 0:
            self.entries.append(FileMeta(data))
        else:
            self.entries.append(DirMeta(data))


class FileData:
    def __init__(self, data: bytes, charset: Optional[str],
                 content_type: str, meta: Optional[FileMeta] = None) -> None:
        self.data = data
        self.charset = charset
        self.content_type = content_type
        self.meta = meta


class Connection:
    def __init__(self, api_key: Optional[APIKey] = None) -> None:
        self.api_key = api_key
        if self.api_key is None:
            with open("isfiles.key") as f:
                self.api_key = APIKey(f.read().strip())
        login, password = self.api_key.raw_api_key.split(':', 1)
        self.auth = (login, password)

    def _get(self, url: str) -> requests.Response:
        try:
            return requests.get(url, auth=self.auth)
        except requests.exceptions.RequestException as ex:
            raise FileAPIException(f"Connection error: {ex}")

    def list_directory(self, path: Union[str, DirMeta]) -> DirMeta:
        """
        Expects an IS path, e.g. /el/fi/podzim2018/IB015/ode/hw12/ or a DirMeta
        object extracted by earlier query. Retuns a DirMeta with single level
        expanded and no file contents.
        """
        if not isinstance(path, str):
            path = path.ispath
        text = self._get('https://is.muni.cz/auth/dok/fmgr_api?'
                         f'url={path};format=json').text
        data = json.loads(text)
        if "chyba" in data:
            emsg = data['chyba']
            raise FileAPIException(f"File manager API error: {emsg}")
        dirmeta = DirMeta(data["uzel"][0])
        if "poduzly" in data["uzel"][0]:
            for i in data["uzel"][0]["poduzly"]["poduzel"]:
                dirmeta._append(i)
        return dirmeta

    def get_file(self, path: Union[str, FileMeta]) -> FileData:
        meta: Optional[FileMeta] = None
        if not isinstance(path, str):
            meta = path
            path = path.ispath
        resp = self._get(f'https://is.muni.cz/auth{path}')
        return FileData(data=resp.content, charset=resp.encoding,
                        content_type=resp.headers.get("content-type",
                                                      "text/plain"),
                        meta=meta)

# vim: colorcolumn=80 expandtab sw=4 ts=4
