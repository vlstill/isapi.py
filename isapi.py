import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import builtins
import re
import sys
from typing import List, Dict, Tuple, Optional

def getkey() -> str:
    with open( "isapikey", "r" ) as f:
        return f.read().strip()

def load( url ):
    try:
        req = urllib.request.urlopen( url )
        if req.status != 200:
            raise ISAPIException( "Error " + str( req.status ) + ": " + req.read() )
    except urllib.error.HTTPError as ex:
        raise ISAPIException( "Error: " + str( ex ) )
    x = ET.fromstring( req.read().decode( "utf-8" ) )
    if x.tag == "CHYBA":
        raise ISAPIException( x.text )
    return x

class ISAPIException ( Exception ):
    pass

def get_raw_data( args ):
    args[ "klic" ] = getkey()
    args[ "fakulta" ] = "1433"
    url = "https://is.muni.cz/export/pb_blok_api?" + urllib.parse.urlencode( args )
    x = load( url )
    return x

class Notebook:
    def __init__( self, name, typ, short ):
        self.name = name
        self.type = typ
        self.short = short

    def __str__( self ):
        return "(blok: name: " + self.name + ", shortname: " + self.short \
                + ", type: " + str( self.type ) + ")"

def get_node( node, childtagname : str, *args ):
    for child in node:
        if child.tag == childtagname:
            if len( args ):
                return get_node( child, *args )
            else:
                return child
    raise ISAPIException( "Could not find childtagname in " + node.tag + "\ntext: " + node.text + "\nitems: " + str( node.items() ) )

def extract( node : str, *args ) -> str:
    return get_node( node, *args ).text


def get_notebooks( course : str ) -> List[Notebook]:
    data = get_raw_data( { "kod": course, "operace": "bloky-seznam" } )
    out = []
    for child in data:
        out.append( Notebook( extract( child, "JMENO" )
                            , int( extract( child, "TYP_ID" ) )
                            , extract( child, "ZKRATKA" )
                            ) )
    return out

class Person:
    def __init__( self, name : str, surname : str, uco : int ) -> None:
        self.name = name
        self.surname = surname
        self.uco = uco

class Course:
    def __init__( self, faculty : str, name : str, teachers : List[Person] ) -> None:
        self.faculty = faculty
        self.name = name
        self.teachers = teachers

def course_info( course : str ) -> Course:
    data = get_raw_data( { "kod": course, "operace": "predmet-info" } )
    teachers = []
    for tutor in get_node( data, "VYUCUJICI_SEZNAM" ):
        teachers.append( Person( extract( tutor, "JMENO" ),
                                 extract( tutor, "PRIJMENI" ),
                                 int( extract( tutor, "UCO" ) ) ) )
    return Course( extract( data, "FAKULTA_ZKRATKA_DOM" ),
                   extract( data, "NAZEV_PREDMETU" ),
                   teachers )


def get_attendance_notebooks( course : str ) -> List[Notebook]:
    return [ x for x in get_notebooks( course ) if x.type == 5 ]


def load_notebook( course : str, shortcut : str ) -> Dict[str, Tuple[str, str]]:
    """
    returns a dict of mappings UCO -> (contents, last_change)
    """
    data = get_raw_data( { "kod": course, "operace": "blok-dej-obsah", "zkratka": shortcut } );
    out : Dict[str, Tuple[str, str]] = {}
    for child in data:
        assert child.tag == "STUDENT"
        skip = 0
        for c in child:
            if c.tag == "NEMA_POZN_BLOK":
                skip = 1
        if skip:
            continue

        uco = extract( child, "UCO" )
        contents = extract( child, "OBSAH" )
        change = extract( child, "ZMENENO" )
        assert uco not in out.keys()

        out[ uco ] = (contents, change)
    return out

starnum = re.compile( "\*[0-9]*\.?[0-9]*" )

def notebook_to_points( contents ):
    def ft( x ):
        if x == "":
            return 0
        return float( x )
    return sum( [ ft( x.group()[1:] ) for x in starnum.finditer( contents ) ] )

def load_points( course, shortcut ):
    """
    returns a dict of mappings UCO -> (pointrs, last_change)
    """
    return dict( [ (k, (notebook_to_points( v[0] ), v[1])) for k, v in load_notebook( course, shortcut ).items() ] )

def students_list( course : str ) -> List[Person]:
    data = get_raw_data( { "kod": course, "operace": "predmet-seznam" } )
    students : List[Person] = []
    for st in data:
        students.append( Person( extract( st, "JMENO" ),
                                 extract( st, "PRIJMENI" ),
                                 int( extract( st, "UCO" ) ) ) )
    return students

def create_notebook( course : str, name : str, short : str ) -> bool:
    try:
        get_raw_data( { "kod": course, "operace": "blok-novy",
                        "jmeno": name, "zkratka": short,
                        "nahlizi": "n", "nedoplnovat": "n", "statistika": "n"
                      } )
        return True
    except ISAPIException:
        return False
