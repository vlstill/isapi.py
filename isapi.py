import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import builtins
import re
import sys

def getkey():
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

def get( args ):
    args[ "klic" ] = getkey()
    args[ "fakulta" ] = "1433"
    url = "https://is.muni.cz/export/pb_blok_api?" + urllib.parse.urlencode( args )
    x = load( url )
    return x

class Blok:
    def __init__( self, name, typ, short ):
        self.name = name
        self.type = typ
        self.short = short

    def __str__( self ):
        return "(blok: name: " + self.name + ", shortname: " + self.short \
                + ", type: " + str( self.type ) + ")"

def extract( node, childtagname ):
    for child in node:
        if child.tag == childtagname:
            return child.text

    raise ISAPIException( "Could not find childtagname in " + node.tag + "\ntext: " + node.text + "\nitems: " + str( node.items() ) )

def bloky( predmet ):
    data = get( { "kod": predmet, "operace": "bloky-seznam" } )
    out = []
    for child in data:
        out.append( Blok( extract( child, "JMENO" )
                        , int( extract( child, "TYP_ID" ) )
                        , extract( child, "ZKRATKA" )
                        ) )
    return out

def prezencniBloky( predmet ):
    return [ x for x in bloky( predmet ) if x.type == 5 ]

def loadBlok( predmet, zkratka ):
    """
    returns a dict of mappings UCO -> (contents, last_change)
    """
    data = get( { "kod": predmet, "operace": "blok-dej-obsah", "zkratka": zkratka } );
    out = {}
    for child in data:
        assert child.tag == "STUDENT"
        skip = 0
        for c in child:
            if c.tag == "NEMA_POZN_BLOK":
                skip = 1
        if skip:
            continue

        uco = extract( child, "UCO" )
        obsah = extract( child, "OBSAH" )
        zmena = extract( child, "ZMENENO" )
        assert uco not in out.keys()

        out[ uco ] = (obsah, zmena)
    return out

starnum = re.compile( "\*[0-9]*\.?[0-9]*" )

def blokToPoints( obsah ):
    def ft( x ):
        if x == "":
            return 0
        return float( x )
    return sum( [ ft( x.group()[1:] ) for x in starnum.finditer( obsah ) ] )

def loadPoints( predmet, zkratka ):
    """
    returns a dict of mappings UCO -> (pointrs, last_change)
    """
    return dict( [ (k, (blokToPoints( v[0] ), v[1])) for k, v in loadBlok( predmet, zkratka ).items() ] )
