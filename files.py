import asyncio
import aiohttp
import json
from iscommon import ISAPIException
from typing import Optional, Union, List
import typing

class APIKey:
	def __init__(self, raw_api_key : str):
		self.raw_api_key = raw_api_key


class FileMeta:
	def __init__(self, data : dict):
		self.dir = False
		self.ispath = data["cesta"]
		self.shortname = data["zkratka"]
		self.name = data.get("nazev")
		self.annotation = data.get("popis")
		self.read = bool(int(data.get("mam_precteno", "0")))
		self.mime : Optional[str] = None
		if "objekty" in data and len(data["objekty"]):	
			obj = data["objekty"]["objekt"][0]
			self.ispath = obj["cesta"]
			if self.name is None:
				self.name = obj["jmeno_souboru"]
			self.shortname = obj["jmeno_souboru"]
			self.mime = obj["mime_type"]
			self.author = obj["vlozil_uco"]
		else:
			self.author = data["zmenil_uco"]


class DirMeta(FileMeta):
	def __init__(self, data : dict):
		FileMeta.__init__(self, data)
		self.dir = True
		self.entries : List[FileMeta] = []

	def _append(self, data):
		if int(data["pocet_poduzlu"]) == 0:
			self.entries.append(FileMeta(data))
		else:
			self.entries.append(DirMeta(data))
		

class FileData:
	def __init__(self, data : bytes, charset : Optional[str], content_type : str, meta : Optional[FileMeta] = None):
		self.data = data
		self.charset = charset
		self.content_type = content_type
		self.meta = meta

class Connection:
	def __init__(self, api_key : Optional[APIKey] = None):
		self.api_key = api_key
		if self.api_key is None:
			with open("isfiles.key") as f:
				self.api_key = APIKey(f.read().strip())
		login, password = self.api_key.raw_api_key.split(':', 1)
		self.auth = aiohttp.BasicAuth(login, password)
		self.session : Optional[aiohttp.ClientSession] = None

	def _get(self, url : str):
		assert self.session is not None
		return self.session.get(url, auth=self.auth)

	async def __aenter__(self):
		assert self.session is None
		self.session = aiohttp.ClientSession()
		await self.session.__aenter__()
		return self

	async def __aexit__(self, type, value, traceback):
		r = await self.session.__aexit__(type, value, traceback)
		self.session = None
		return r

	async def list_directory(self, path : Union[str, DirMeta]) -> DirMeta:
		"""
		Expects an IS path, e.g. /el/fi/podzim2018/IB015/ode/hw12/ or a DirMeta
		object extracted by earlier query. Retuns a DirMeta with single level
		expanded and no file contents.
		"""
		if not isinstance(path, str):
			path = path.ispath
		async with self._get(f'https://is.muni.cz/auth/dok/fmgr_api?url={path};format=json') as resp:
			text = await resp.text()
			data = json.loads(text)
			if "chyba" in data:
				raise ISAPIException(f"File manager API error: {data['chyba']}")
			dirmeta = DirMeta(data["uzel"][0])
			for i in data["uzel"][0]["poduzly"]["poduzel"]:
				dirmeta._append(i)
			return dirmeta

	async def get_file(self, path : Union[str, FileMeta]) -> FileData:
		meta : Optional[FileMeta] = None
		if not isinstance(path, str):
			meta = path
			path = path.ispath
		async with self._get(f'https://is.muni.cz/auth{path}') as resp:
			return FileData(data=await resp.read(), charset=resp.charset,
							content_type=resp.content_type, meta=meta)


def sync_list_directory(path : str, api_key : Optional[APIKey] = None) -> DirMeta:
	async def ld() -> DirMeta:
		async with Connection(api_key) as conn:
			return typing.cast(DirMeta, await conn.list_directory(path))
	return asyncio.run(ld())

def sync_get_file(path : str, api_key : Optional[APIKey] = None) -> FileData:
	async def gf() -> FileData:
		async with Connection(api_key) as conn:
			return typing.cast(FileData, await conn.get_file(path))
	return asyncio.run(gf())
