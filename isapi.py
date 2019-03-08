import requests
import xml.etree.ElementTree as ET
import re
from typing import List, Dict, Tuple, Optional
import datetime
from tzlocal import get_localzone
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


def getkey(path) -> Optional[str]:
    try:
        with open(os.path.join(path, "isapikey"), "r") as f:
            return f.read().strip()
    except Exception:
        return None


def __get_node(node : ET.Element, childtagname : str, *args) -> ET.Element:
    for child in node:
        if child.tag == childtagname:
            if len(args):
                return __get_node(child, *args)
            else:
                return child
    raise ISAPIException(
              "Could not find childtagname in {}\ntext: {}\nitems: {}"
              .format(node.tag, node.text, node.items()))


def __extract(node : ET.Element, *args) -> str:
    t = __get_node(node, *args).text
    if t is None:
        return ""
    return t


class IS:
    STARNUM = re.compile(r"\*[0-9]*\.?[0-9]*")

    def __init__(self, course : str = None, faculty = None, api_key : Optional[str] = None) -> None:
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
            if k not in args:
                args[k] = v
        base_url = "https://is.muni.cz/export/pb_blok_api"
        req = requests.post(base_url, args)
        if req.status_code != 200:
            raise ISAPIException("Error {} {}".format(req.status_code, req.reason))
        x = ET.fromstring(req.text)
        if x.tag == "CHYBA":
            raise ISAPIException(x.text)
        return x

    def get_notebooks(self, course : str) -> List[Notebook]:
        data = self.__raw_req({"kod": course, "operace": "bloky-seznam"})
        out = []
        for child in data:
            out.append(Notebook(__extract(child, "JMENO"),
                                int(__extract(child, "TYP_ID")),
                                __extract(child, "ZKRATKA")))
        return out

    def course_info(self, course : str) -> Course:
        data = self.__raw_req({"kod": course, "operace": "predmet-info"})
        teachers = []
        for tutor in __get_node(data, "VYUCUJICI_SEZNAM"):
            teachers.append(Person(__extract(tutor, "JMENO"),
                                   __extract(tutor, "PRIJMENI"),
                                   int(__extract(tutor, "UCO"))))
        return Course(__extract(data, "FAKULTA_ZKRATKA_DOM"),
                      __extract(data, "NAZEV_PREDMETU"),
                      teachers)

    def get_attendance_notebooks(self, course : str) -> List[Notebook]:
        return [x for x in self.get_notebooks(course) if x.type == 5]

    def load_notebook(self, course : str, shortcut : str)\
                      -> Dict[str, Tuple[str, str]]:
        """
        returns a dict of mappings UCO -> (contents, last_change)
        """
        data = self.__raw_req({"kod": course, "operace": "blok-dej-obsah",
                                    "zkratka": shortcut})
        out : Dict[str, Tuple[str, str]] = {}
        for child in data:
            assert child.tag == "STUDENT"
            skip = False
            for c in child:
                if c.tag == "NEMA_POZN_BLOK":
                    skip = True
            if skip:
                continue

            uco = __extract(child, "UCO")
            contents = __extract(child, "OBSAH")
            change = __extract(child, "ZMENENO")
            assert uco not in out.keys()

            out[uco] = (contents, change)
        return out

    def notebook_to_points(self, contents):
        def ft(x):
            if x == "":
                return 0
            return float(x)
        return sum([ft(x.group()[1:]) for x in STARNUM.finditer(contents)])

    def load_points(self, course, shortcut):
        """
        returns a dict of mappings UCO -> (pointrs, last_change)
        """
        return dict([(k, (notebook_to_points(v[0]), v[1]))
                     for k, v in load_notebook(course, shortcut).items()])

    def students_list(self, course : str) -> List[Person]:
        data = self.__raw_req({"kod": course, "operace": "predmet-seznam"})
        students : List[Person] = []
        for st in data:
            students.append(Person(__extract(st, "JMENO"),
                                   __extract(st, "PRIJMENI"),
                                   int(__extract(st, "UCO"))))
        return students

    def create_notebook(self, course : str, name : str, short : str) -> bool:
        try:
            self.__raw_req({"kod": course, "operace": "blok-novy",
                                 "jmeno": name, "zkratka": short,
                                 "nahlizi": "n", "nedoplnovat": "n", "statistika": "n"})
            return True
        except ISAPIException:
            return False

    def store(self, course : str, short : str, uco : str, contents : str,
              timestamp : Optional[datetime.datetime] = None, overwrite = False)\
              -> None:
        args = {"kod": course, "operace": "blok-pis-student-obsah",
                "zkratka": short, "uco": uco, "obsah": contents}
        if overwrite:
            args['prepis'] = 'a'
        if timestamp is not None:
            args['poslzmeneno'] = serialize_date(timestamp)
        self.__raw_req(args)


def parse_date(date : str) -> datetime.datetime:
    raw = datetime.datetime(year = int(date[:4]),
                            month = int(date[4:6]),
                            day = int(date[6:8]),
                            hour = int(date[8:10]),
                            minute = int(date[10:12]),
                            second = int(date[12:14]))
    tz = get_localzone()
    return tz.localize(raw, is_dst=None)


def serialize_date(date : datetime.datetime) -> str:
    return "%04d%02d%02d%02d%02d%02d" % (date.year, date.month, date.day,
                                         date.hour, date.minute, date.second)
