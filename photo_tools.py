import functools
import operator
import os
import re
from glob import glob
from itertools import cycle
from math import asin, sqrt, sin, cos

import folium
import numpy as np
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import piexif
from sklearn.cluster import DBSCAN


def get_exif_data(image):
    """
    Returns a dictionary from the exif data of an PIL Image item. Also converts the GPS Tags.
    :param image:
    """
    exif_data = {}
    info = image._getexif()
    if info:
        for tag, value in info.items():
            decoded = TAGS.get(tag, tag)
            if decoded == "GPSInfo":
                gps_data = {}
                if type(value) == dict or type(value) == list:
                    for t in value:
                        sub_decoded = GPSTAGS.get(t, t)
                        gps_data[sub_decoded] = value[t]
                else:
                    gps_data = {}

                exif_data[decoded] = gps_data
            else:
                exif_data[decoded] = value
    return exif_data


def _get_if_exist(data, key):
    if key in data:
        return data[key]

    return None


def _convert_to_degrees(value):
    """
    Helper function to convert the GPS coordinates stored in the EXIF to degrees in float format.

    """
    d0 = value[0][0]
    d1 = value[0][1]
    d = float(d0) / float(d1)

    m0 = value[1][0]
    m1 = value[1][1]
    m = float(m0) / float(m1)

    s0 = value[2][0]
    s1 = value[2][1]
    s = float(s0) / float(s1)

    return d + (m / 60.0) + (s / 3600.0)


def _determine_reference_gps(name, value):
    ref_dict = {"latitude": {0: "N", 1: "S"}, "longitude": {0: "E", 1: "W"}}
    if value < 0:
        ref_flag = 1
        value = 0 - value
    else:
        ref_flag = 0

    return ref_dict[name][ref_flag], value


def _convert_from_degrees(value):
    """
    Helper function to convert float format GPS to format used in EXIF.
    :param value:
    :return:
    """
    degrees = int(value)
    temp = value - degrees
    temp = temp * 3600
    minutes = int(temp / 60)
    seconds = temp - minutes * 60
    return degrees, minutes, seconds


def _format_gps(name, value):
    ref, value = _determine_reference_gps(name, value)
    degrees, minutes, seconds = _convert_from_degrees(value)
    return ref, ((degrees, 1), (minutes, 1), (int(seconds * 10000), 10000))


def fake_exif(image: Image, lat_long: list, datetime: str, fname: str):
    """
    Fake exif tag formatted gps data.
    :param fname:
    :param datetime:
    :param image:
    :param lat_long: list of longitude and latitude
    :return: dictionary
    """
    lat, long = lat_long

    # Load existing exif dict
    if 'exif' in image.info.keys():
        exif_dict = piexif.load(image.info['exif'])
    else:
        exif_dict = dict()

    # Modify GPS section
    gps_ifd = dict()
    gps_ifd[piexif.GPSIFD.GPSVersionID] = (2, 0, 0, 0)
    gps_ifd[piexif.GPSIFD.GPSAltitudeRef] = 1
    gps_ifd[piexif.GPSIFD.GPSMapDatum] = 'WGS-84'
    gps_ifd[piexif.GPSIFD.GPSLatitudeRef], gps_ifd[piexif.GPSIFD.GPSLatitude] = _format_gps("latitude", lat)
    gps_ifd[piexif.GPSIFD.GPSLongitudeRef], gps_ifd[piexif.GPSIFD.GPSLongitude] = _format_gps("longitude", long)
    exif_dict['GPS'] = gps_ifd

    zeroth_ifd = dict()
    zeroth_ifd[306] = datetime
    exif_dict['0th'] = zeroth_ifd

    exif_bytes = piexif.dump(exif_dict)
    image.save(fname, "jpeg", exif=exif_bytes)


def get_lat_lon(exif_data: dict):
    """
    Returns the latitude and longitude, if available, from the provided exif_data (obtained through get_exif_data above)
    """
    lat = None
    lon = None

    if "GPSInfo" in exif_data:
        gps_info = exif_data["GPSInfo"]

        gps_latitude = _get_if_exist(gps_info, "GPSLatitude")
        gps_latitude_ref = _get_if_exist(gps_info, 'GPSLatitudeRef')
        gps_longitude = _get_if_exist(gps_info, 'GPSLongitude')
        gps_longitude_ref = _get_if_exist(gps_info, 'GPSLongitudeRef')

        if gps_latitude and gps_latitude_ref and gps_longitude and gps_longitude_ref:
            lat = _convert_to_degrees(gps_latitude)
            if gps_latitude_ref != "N":
                lat = 0 - lat

            lon = _convert_to_degrees(gps_longitude)
            if gps_longitude_ref != "E":
                lon = 0 - lon

    return lat, lon


def get_datum(exif_data: dict):
    """
    Returns exif datetime.
    :param exif_data:
    :return:
    """
    datum = None

    if "DateTime" in exif_data:
        datum = exif_data["DateTime"]
    return datum


def avg_datetime(arr):
    """
    See
    https://stackoverflow.com/a/27908346
    Obsolete, now the minimum datetime is used per group for sorting
    :param arr:
    :return:
    """
    dt_min = arr.min()
    deltas = [x - dt_min for x in arr]
    return dt_min + functools.reduce(operator.add, deltas) / len(deltas)


def lat_long_distance(x, y):
    """
    Returns the distance in km between two points given in latitude/longitude.

    See
    http://edwilliams.org/avform.htm#Dist
    Distance between points
    :param x:
    :param y:
    :return:
    """
    lat1, lon1 = np.deg2rad(x)
    lat2, lon2 = np.deg2rad(y)
    # radius of earth im km
    r = 6373
    return 2 * asin(sqrt((sin((lat1 - lat2) / 2)) ** 2 +
                         cos(lat1) * cos(lat2) * (sin((lon1 - lon2) / 2)) ** 2)) * r


def get_photo_exif(pic_path: str) -> np.array:
    """
    Extract exif information of all pictures in given directory. Return picture paths, locations and datetimes as three
    separate arrays.
    :param pic_path: Picture directory
    :return:
    """
    all_file_list = glob(os.path.join(pic_path, "*.jpg"))
    file_list = []
    location_list = []
    datetime_list = []

    for i, file_name in enumerate(all_file_list):
        image = Image.open(file_name)
        exif_data = get_exif_data(image)
        latitude, longitude = get_lat_lon(exif_data)
        datum = get_datum(exif_data)
        if latitude and datum:
            file_list.append(file_name)
            location_list.append([latitude, longitude])
            # format is for some reason '2019:07:28 16:32:47'
            # change to '2019-07-28 16:32:47'
            datetime_list.append(re.sub(":", "-", string=datum, count=2))
        else:
            pass

    return np.array(file_list), np.array(location_list), np.array(datetime_list).astype('datetime64')


def get_labels(x, min_dist, times):
    """
    Return labels for clusters given locations in latitude/longitude and minimum distance.

    Example:
    >> locs = [[22.27676994, 114.1246085 ],
    >>         [ 35.69486589, 139.78645639],
    >>         [ 35.24504731, 139.05225117]]
    >> min_dist = 5
    >> get_labels(locs, min_dist)

    :param times:
    :param x:
    :param min_dist:
    :return:
    """
    # cluster with user defined distance metric suitable for latitude/ longitude features
    # distance between points of one cluster min. 5 km
    db = DBSCAN(eps=min_dist, min_samples=1, metric=lat_long_distance).fit(x)

    cluster_labels = db.labels_

    # map cluster labels to time sorted labelling of clusters, i.e. cluster around
    # 2019-07-01 has label 0, cluster around 2019-07-28 has cluster 1, ...
    # and map original cluster labels to time sorted labels
    avg_time = [min(times[np.where(cluster_labels == i)]) for i in range(max(cluster_labels) + 1)]
    time_dict = dict(zip(np.argsort(avg_time), range(max(cluster_labels) + 1)))

    vf = np.vectorize(lambda z: time_dict[z])

    labels = vf(cluster_labels)
    return labels


def get_label_colors(labels):
    """
    Map cluster labels to accepted colors for folium icons.
    :param labels:
    :return:
    """
    unique_labels = max(labels) + 1

    color_cycle = cycle(['red', 'darkred', 'orange', 'green', 'darkgreen', 'blue', 'purple', 'darkpurple', 'cadetblue'])
    colors = list()
    i = 0
    while i < max(labels) + 1:
        colors.append(next(color_cycle))
        i += 1
    color_dict = dict(zip(range(unique_labels), colors))
    color_dict[-1] = "black"
    return color_dict


def get_map(lat_long, save, colors=None):
    """
    Create map and scale to fit minimum and maximum values of latitude/ longitude

    :param colors:
    :param save:
    :param lat_long:
    :return:
    """
    m = folium.Map(tiles='Stamen Terrain', template='map_view.html')

    min_lat, min_long = lat_long.min(axis=0)
    max_lat, max_long = lat_long.max(axis=0)
    m.fit_bounds(bounds=[[min_lat, min_long], [max_lat, max_long]], max_zoom=12)

    # Put markers where photos were taken
    if colors is not None:
        for i, loc in enumerate(lat_long):
            folium.Marker(loc,
                          icon=folium.Icon(color=colors[i], icon='flag')
                          ).add_to(m)
    else:
        for i, loc in enumerate(lat_long):
            folium.Marker(loc).add_to(m)
    # Save map as html or return map object
    if not save:
        return m
    else:
        m.save('templates/map.html')
        return None


def clear_images(stat_dir="./static/images"):
    """
    Clear symbolic links in given directory (static directory of website).
    :param stat_dir:
    :return:
    """
    for file in glob(os.path.join(stat_dir, "*.jpg")):
        os.unlink(file)


def link_images(src_dir, dst_dir="./static/images"):
    """
    Create symbolic links to source directory *.jpg files in destination directory.
    :param src_dir:
    :param dst_dir:
    :return:
    """
    for file in glob(os.path.join(src_dir, '*.jpg')):
        basename = os.path.basename(file)
        os.symlink(file, os.path.join(dst_dir, basename))


def filter_cluster(x, n: int, cluster_labels):
    """
    Filter array (one of FILES, LOCS, TIMES) or list (table) to contain points belonging to cluster number n.
    :param cluster_labels:
    :param x:
    :param n:
    :return:
    """
    if type(x) == np.ndarray:
        return x[np.where(cluster_labels == n)]
    elif type(x) == list:
        return [x[i] for i in np.where(cluster_labels == n)[0]]


def sort_cluster(x: list, t: np.ndarray) -> list:
    """
    sort x according to t
    :param x:
    :param t:
    :return:
    """
    return [x[i] for i in np.argsort(t)]
