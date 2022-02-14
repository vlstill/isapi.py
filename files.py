import posixpath
import requests
import requests.exceptions
import json
import logging
import pprint

from dateutil.parser import isoparse
from enum import Enum, auto
from json.decoder import JSONDecodeError
from typing import Optional, Union, List
from isapi.iscommon import localize_timestamp, ISAPIException


class FileAPIException(ISAPIException):
    def __init__(self, message: str, api_error: Optional[str] = None) -> None:
        super().__init__(message)
        self.api_error = api_error


class FileDoesNotExistException(FileAPIException):
    pass


class IsDirectoryException(FileAPIException):
    pass


class APIKey:
    def __init__(self, raw_api_key: str) -> None:
        self.raw_api_key = raw_api_key


class FileMeta:
    def __init__(self, data: dict, logger: logging.Logger) -> None:
        self.logger = logger
        self.dir = False
        self.ispath = data["cesta"]
        self.shortname = data["zkratka"]
        self.name = data.get("nazev")
        self.annotation = data.get("popis")
        self.read = bool(int(data.get("mam_precteno", "0")))
        if "objekty" in data and len(data["objekty"]):
            obj = data["objekty"]["objekt"][0]
            self.ispath = obj["cesta"]
            if self.name is None:
                self.name = obj["jmeno_souboru"]
            self.shortname = obj["jmeno_souboru"]
            self.mime: Optional[str] = obj["mime_type"]
            self.author = int(obj["vlozil_uco"])
            self.change_time = localize_timestamp(isoparse(obj["vlozeno"]))
            self.objid: Optional[int] = int(obj["objekt_id"])
            if len(data["objekty"]) > 1:
                self.logger.warning("Found node with more then one object:\n"
                                    + pprint.pformat(data))
        else:
            if int(data["pocet_poduzlu"]) == 0:
                # not a dir
                self.logger.warning("Found node without objects:\n"
                                    + pprint.pformat(data))
            self.mime = None
            self.author = int(data["zmenil_uco"])
            self.change_time = localize_timestamp(isoparse(data["zmeneno"]))
            self.objid = None

    def __repr__(self) -> str:
        return f"is.muni.cz:{self.ispath}"

    def __str__(self) -> str:
        return repr(self)


class DirMeta(FileMeta):
    def __init__(self, data: dict, logger: logging.Logger) -> None:
        super().__init__(data, logger)
        self.dir = True
        self.entries: List[FileMeta] = []

    def _append(self, data: dict) -> None:
        self.entries.append(_meta_from_raw(data, self.logger))


def _meta_from_raw(raw: dict, logger: logging.Logger) -> FileMeta:
    if int(raw["pocet_poduzlu"]) == 0:
        return FileMeta(raw, logger)
    else:
        return DirMeta(raw, logger)


class FileData:
    def __init__(self, data: bytes, charset: Optional[str],
                 content_type: str, meta: Optional[FileMeta] = None) -> None:
        self.data = data
        self.charset = charset
        self.content_type = content_type
        self.meta = meta


class OnConflict(Enum):
    Error = auto()
    Overwrite = auto()
    Rename = auto()

    def to_is(self) -> str:
        if self is OnConflict.Error:
            return "er"
        if self is OnConflict.Overwrite:
            return "wr"
        if self is OnConflict.Rename:
            return "re"


class Connection:
    def __init__(self, api_key: Optional[APIKey] = None) -> None:
        self.api_key = api_key
        if self.api_key is None:
            with open("isfiles.key") as f:
                self.api_key = APIKey(f.read().strip())
        login, password = self.api_key.raw_api_key.split(':', 1)
        self.auth = (login, password)
        self.logger = logging.getLogger("isapi.py/files")
        self.logger.debug("IS Files connection initialized")

    def _get(self, url: str) -> requests.Response:
        try:
            return requests.get(url, auth=self.auth)
        except requests.exceptions.RequestException as ex:
            self.logger.warning("File API conncetion error", exc_info=True)
            raise FileAPIException(f"Connection error: {ex}")

    def _rfmgr(self, args: dict, files: Optional[dict] = None) -> dict:
        if files is None:
            files = {}
        # IS breaks if directory URL does not end with /
        if "furl" in args and not args["furl"].endswith("/"):
            args["furl"] += "/"
        for k in list(args):
            if args[k] is None:
                del args[k]

        try:
            rsp = requests.post("https://is.muni.cz/auth/dok/rfmgr.pl",
                                data=args, files=files, auth=self.auth)
        except requests.exceptions.RequestException as ex:
            self.logger.error(f"File API conncetion error args = {args}, "
                              f"req = {ex.request}", exc_info=True)
            raise FileAPIException(f"Connection error: {ex}")

        if rsp.status_code != 200:
            self.logger.warning("File API conncetion error: "
                                f"status {rsp.status_code}")
            raise FileAPIException("rfmgr.pl returned HTTP code "
                                   f"{rsp.status_code}")

        if rsp.text.startswith("Majitel neosobního účtu"):
            self.logger.error(f"File API account error {rsp.text}")
            raise FileAPIException("rfmgr.pl API error: not permitted, "
                                   "see IS non-personal account settings")

        if not rsp.text.startswith("{"):
            self.logger.error(f"File API account error: {rsp.text}")
            raise FileAPIException("rfmgr.pl API error: unexpected result"
                                   "format, probably bad request")

        data: dict = json.loads(rsp.text)
        if "chyba" in data:
            self.logger.warning(f"File API error: {data['chyba']}")
            raise FileAPIException(f"rfmgr.pl API error: {data['chyba']}",
                                   api_error=data['chyba'])

        return data

    def _get_info(self, path: Union[str, FileMeta]) -> dict:
        if not isinstance(path, str):
            path = path.ispath
        assert isinstance(path, str)
        text = self._get('https://is.muni.cz/auth/dok/fmgr_api?'
                         f'url={path};format=json').text
        try:
            data = json.loads(text)
        except JSONDecodeError:
            self.logger.error(f"File API error: invalid reply {text}")
            raise FileAPIException("Invalid reply format, probably forbidden "
                                   f"access:\n{text}")
        assert isinstance(data, dict)
        if "chyba" in data:
            emsg = data['chyba']
            if emsg == 'Zadaná složka nebo soubor nebyl nalezen.':
                raise FileDoesNotExistException(path)
            self.logger.error(f"File API error: {emsg}")
            raise FileAPIException(f"File manager API error: {emsg}")
        return data

    def list_directory(self, path: Union[str, DirMeta]) -> DirMeta:
        """
        Expects an IS path, e.g. /el/fi/podzim2018/IB015/ode/hw12/ or a DirMeta
        object extracted by earlier query. Retuns a DirMeta with single level
        expanded and no file contents.
        """
        data = self._get_info(path)
        dirmeta = DirMeta(data["uzel"][0], self.logger)
        if "poduzly" in data["uzel"][0]:
            for i in data["uzel"][0]["poduzly"]["poduzel"]:
                dirmeta._append(i)
        return dirmeta

    def file_info(self, path: Union[str, FileMeta]) -> FileMeta:
        raw = self._get_info(path)
        return _meta_from_raw(raw["uzel"][0], self.logger)

    def get_file(self, path: Union[str, FileMeta]) -> FileData:
        if not isinstance(path, str):
            path = path.ispath
        assert isinstance(path, str)
        resp = self._get(f'https://is.muni.cz/auth{path}')
        # get meta after the file was downloaded, file download cannot get 404,
        # but this can
        meta = self.file_info(path)
        if meta.dir:
            raise IsDirectoryException(path)
        return FileData(data=resp.content, charset=resp.encoding,
                        content_type=resp.headers.get("content-type",
                                                      "text/plain"),
                        meta=meta)

    def upload_file(self, file_path: str, is_path: str,
                    as_path: Optional[str] = None,
                    long_name: Optional[str] = None,
                    description: Optional[str] = None,
                    on_conflict: OnConflict = OnConflict.Error) -> None:
        if as_path is None:
            as_path = posixpath.basename(file_path)
        basename = posixpath.basename(as_path)
        # dirname returns '' without dir
        furl = posixpath.normpath(posixpath.join(is_path,
                                  posixpath.dirname(as_path)))

        self._rfmgr({"op": "vlso",
                     "furl": furl,
                     "jmeno_souboru_0": basename,
                     "nazev_0": long_name,
                     "popis_0": description,
                     "kolize": on_conflict.to_is()},
                    {"FILE_0": (basename, open(file_path, 'rb'))}),

    EXISTS_MSG = "Složka s tímto názvem již existuje"
    SHORT_EXISTS_MSG = "Pokoušíte se použít zkratku, která již v této složce "\
                       "existuje."

    def mkdir(self, is_path: str, long_name: Optional[str] = None,
              description: Optional[str] = None) -> bool:
        "Returns true if the dir was actually returned."
        while is_path[-1:] == "/":
            is_path = posixpath.dirname(is_path)
        dirname = posixpath.basename(is_path)
        path = posixpath.dirname(is_path)

        try:
            self._rfmgr({"op": "vlsl",
                         "furl": path,
                         "zkratka_1": dirname,
                         "nazev_1": long_name or dirname,
                         "popis_1": description})
            return True
        except FileAPIException as ex:
            if ex.api_error \
                    and (Connection.EXISTS_MSG in ex.api_error
                         or Connection.SHORT_EXISTS_MSG in ex.api_error):
                return False
            raise

    def upload_zip(self, is_path: str, zip_path: str,
                   use_metadata: bool = False,
                   ignore_top_level_dir: bool = False,
                   overwrite: bool = False) -> None:
        args = {"op": "imzi",
                "furl": is_path,
                "servis": "a" if use_metadata else "n",
                "filename": "upload.zip"}
        # IS does seem to ignore value of these arguments and just look if they
        # are present
        if ignore_top_level_dir:
            args["igntop"] = "a"
        if overwrite:
            args["prep"] = "a"
        self._rfmgr(args,
                    {"FILE": ("upload.zip", open(zip_path, 'rb'),
                              "application/x-zip-compressed")})


# vim: colorcolumn=80 expandtab sw=4 ts=4
