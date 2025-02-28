import pandas as pd
import geopandas as gpd
from sqlalchemy import create_engine  

# dissolve EAs by CTUID

def ea_dissolve():

    db_connection_url = "postgresql://postgres:postgres@localhost:5432/census"
    con = create_engine(db_connection_url)  

    sql = """
    SELECT * FROM in_1971_ea_jct;
    """
    ea = gpd.read_postgis(sql, con)

    ct = ea.dissolve(by = "ctuid71new")

    ct = ct[["cmauid_71","cmauid_11","ctuid71","geom"]]

    ct.to_file("data/ct_71_dissolved_ea.shp")

# dissolve CTs by CMAUID

def ct_dissolve():

    ct = gpd.read_file("data/ct_71_dissolved_ea.shp")

    cma = ct.dissolve(by = "cmauid_11")

    cma = cma[["cmauid_71", "geometry"]]

    cma.to_file("data/cma_71.geojson")


# ea_dissolve()

ct_dissolve()