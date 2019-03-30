import requests
import xml.etree.ElementTree as ET
import re
from typing import List, Dict, Tuple, Optional
import datetime
from tzlocal import get_localzone # type: ignore
import os.path


class ISAPIException (Exception):
    pass


class Person:
    def __init__(self, name : str, surname : str, uco : int) -> None:
        self.name = name
        self.surname = surname
        self.uco = uco


class Course:
    def __init__(self, faculty : str, name : str, teachers : List[Person])\
                 -> None:
        self.faculty = faculty
        self.name = name
        self.teachers = teachers


class Notebook:
    def __init__(self, name : str, typ : int, short : str) -> None:
        self.name = name
        self.type = typ
        self.short = short

    def __str__(self) -> str:
        return "(blok: name: " + self.name + ", shortname: " + self.short \
                + ", type: " + str(self.type) + ")"


def getkey(path : str) -> Optional[str]:
    """
    Try to parse api key from given directory from file name "isapikey".
    """
    try:
        with open(os.path.join(path, "isapikey"), "r") as f:
            return f.read().strip()
    except Exception:
        return None


def _get_node(node : ET.Element, childtagname : str, *args : str) -> ET.Element:
    for child in node:
        if child.tag == childtagname:
            if len(args):
                return _get_node(child, *args)
            else:
                return child
    raise ISAPIException(
              "Could not find childtagname in {}\ntext: {}\nitems: {}"
              .format(node.tag, node.text, node.items()))


def _extract(node : ET.Element, *args : str) -> str:
    t = _get_node(node, *args).text
    if t is None:
        return ""
    return t


class Entry:
    STARNUM = re.compile(r"\*[0-9]*\.?[0-9]*")

    def __init__(self, text : str, timestamp : Optional[datetime.datetime] = None) -> None:
        self.text = text
        self.timestamp = timestamp

    def points(self) -> float:
        def ft(x : str) -> float:
            if x == "":
                return 0
            return float(x)
        return sum([ft(x.group()[1:]) for x in Entry.STARNUM.finditer(self.text)])


class Connection:

    def __init__(self, course : Optional[str] = None,
                 faculty : Optional[str] = None,
                 api_key : Optional[str] = None) -> None:
        """
        Initialize a new instance.
        Course has to be set.
        The api_key has to either be in isapikey file in the working directory,
        or provided.
        The default faculty is FI.
        """
        if api_key is None:
            api_key = getkey(".")
        self.__DEFARGS = {"klic": api_key,
                          "fakulta": "1433",
                         }
        if course is not None:
            self.__DEFARGS['kod'] = course
        if faculty is not None:
            self.__DEFARGS['fakulta'] = faculty

    def __raw_req(self, args : dict) -> ET.Element:
        for k, v in self.__DEFARGS.items():
            if k not in args or args[k] is None:
                args[k] = v
        base_url = "https://is.muni.cz/export/pb_blok_api"
        assert args['kod'] is not None, "Course id not set"
        assert args['klic'] is not None, "API key not set"

        req = requests.post(base_url, args)
        if req.status_code != 200:
            raise ISAPIException("Error {} {}".format(req.status_code, req.reason))
        x = ET.fromstring(req.text)
        if x.tag == "CHYBA":
            raise ISAPIException(x.text)
        return x

    def notebooks(self, course : Optional[str] = None) -> List[Notebook]:
        """
        Get a list of notebooks for a given course.
        If the course was set in constructor, it does not need to be set here.
        """
        data = self.__raw_req({"kod": course, "operace": "bloky-seznam"})
        out = []
        for child in data:
            out.append(Notebook(_extract(child, "JMENO"),
                                int(_extract(child, "TYP_ID")),
                                _extract(child, "ZKRATKA")))
        return out

    def course_info(self, course : Optional[str] = None) -> Course:
        """
        Get information about a course, this includes lists of teachers.
        """
        data = self.__raw_req({"kod": course, "operace": "predmet-info"})
        teachers = []
        for tutor in _get_node(data, "VYUCUJICI_SEZNAM"):
            teachers.append(Person(_extract(tutor, "JMENO"),
                                   _extract(tutor, "PRIJMENI"),
                                   int(_extract(tutor, "UCO"))))
        return Course(_extract(data, "FAKULTA_ZKRATKA_DOM"),
                      _extract(data, "NAZEV_PREDMETU"),
                      teachers)

    def attendance_notebooks(self, course : Optional[str] = None) -> List[Notebook]:
        """
        Get list of notebooks used for attendance tracking.
        """
        return [x for x in self.notebooks(course) if x.type == 5]

    def notebook(self, shortcut : str, course : Optional[str] = None)\
                      -> Dict[int, Entry]:
        """
        Returns a mappings UCO -> Entry
        """
        data = self.__raw_req({"kod": course, "operace": "blok-dej-obsah",
                                    "zkratka": shortcut})
        out : Dict[int, Entry] = {}
        for child in data:
            assert child.tag == "STUDENT"
            skip = False
            for c in child:
                if c.tag == "NEMA_POZN_BLOK":
                    skip = True
            if skip:
                continue

            uco = int(_extract(child, "UCO"))
            contents = _extract(child, "OBSAH")
            change = _extract(child, "ZMENENO")
            assert uco not in out.keys()

            out[uco] = Entry(contents, parse_date(change))
        return out

    def students_list(self, course : Optional[str] = None) -> List[Person]:
        """
        Get a list of students.
        """
        data = self.__raw_req({"kod": course, "operace": "predmet-seznam"})
        students : List[Person] = []
        for st in data:
            students.append(Person(_extract(st, "JMENO"),
                                   _extract(st, "PRIJMENI"),
                                   int(_extract(st, "UCO"))))
        return students

    def create_notebook(self, name : str, short : str, course : Optional[str] = None) -> bool:
        """
        Creates a new notebook given its name and shortcut.
        """
        try:
            self.__raw_req({"kod": course, "operace": "blok-novy",
                            "jmeno": name, "zkratka": short,
                            "nahlizi": "n", "nedoplnovat": "n", "statistika": "n"})
            return True
        except ISAPIException:
            return False

    def store(self, short : str, uco : int, entry : Entry, course : Optional[str],
              overwrite : bool = False)\
              -> None:
        """
        Writes given (modified) entry to IS, the update is by default works
        only if timestamp in the entry matches timestamp in IS or if there is
        no entry in IS. Optionally overwritting existing data unconditionally.
        """
        args = {"kod": course, "operace": "blok-pis-student-obsah",
                "zkratka": short, "uco": str(uco), "obsah": entry.text}
        if overwrite:
            args['prepis'] = 'a'
        if entry.timestamp is not None:
            args['poslzmeneno'] = serialize_date(entry.timestamp)
        self.__raw_req(args)


    @staticmethod
    def parse_date(date : str) -> datetime.datetime:
        raw = datetime.datetime(year = int(date[:4]),
                                month = int(date[4:6]),
                                day = int(date[6:8]),
                                hour = int(date[8:10]),
                                minute = int(date[10:12]),
                                second = int(date[12:14]))
        tz = get_localzone()
        return tz.localize(raw, is_dst=None) # type: ignore


    @staticmethod
    def serialize_date(date : datetime.datetime) -> str:
        return "%04d%02d%02d%02d%02d%02d" % (date.year, date.month, date.day,
                                             date.hour, date.minute, date.second)

def serialize_date(date : datetime.datetime) -> str:
    return Connection.serialize_date(date)


def parse_date(date : str) -> datetime.datetime:
    return Connection.parse_date(date)
