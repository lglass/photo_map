"""
Usage:

Start the flask server by running:

    $ python flask_app.py

And then head to http://localhost:9750/ in your browser.
"""
import sys

from flask import Flask, render_template, redirect, request

from pager import Pager
from photo_tools import *

if len(sys.argv) < 2:
    print("Command line input for photo directory missing\nPlease call\n$ python flask_app.py PHOTO_DIR")
    exit()

PHOTO_DIR = sys.argv[1]
APPNAME = "Photo Map"
STATIC_DIR = "static"
clear_images()
link_images(PHOTO_DIR)

# Load data necessary to display
file_names, locations, timestamps = get_photo_exif(os.path.join(STATIC_DIR, "images"))
# Compute clusters from gps data stored in LOCS
if len(locations) > 0:
    # TODO: change static min_dist of 5 km to user input
    cluster_labels = get_labels(locations, 5, timestamps)
    colors_dict = get_label_colors(cluster_labels)
    cluster_colors = [colors_dict[i] for i in cluster_labels]
else:
    print("No GPS data could be parsed for provided photos.")
    exit()

# table is equivalent to files but has an easy handover to html
table = [{'name': os.path.join('images', os.path.basename(p))} for p in file_names]
table_group = table
# pagers that help update the page, Pager class defined in pager.py
photoPager = Pager(len(file_names))
groupPager = Pager(max(cluster_labels) + 1)

# Start flask app
app = Flask(__name__, static_folder=STATIC_DIR)
app.config.update(APPNAME=APPNAME)


@app.route('/')
def index():
    global groupPager
    global photoPager
    # reset pagers on return to index
    groupPager.current = 0
    photoPager.current = 0
    folium_map = get_map(locations, save=True, colors=cluster_colors)
    return render_template('map_view.html',
                           groupPager=groupPager,
                           photoPager=photoPager)


@app.route("/map/<int:map_ind>/")
def map_view(map_ind):
    global groupPager
    global photoPager
    global table_group
    if map_ind >= groupPager.count:
        return render_template("404.html"), 404
    else:
        time_group = filter_cluster(timestamps, map_ind, cluster_labels)
        table_group = sort_cluster(filter_cluster(table, map_ind, cluster_labels), time_group)
        # set photo pager to only page through images contained in group
        photoPager = Pager(len(table_group))
        photoPager.current = 0
        groupPager.current = map_ind
        group_locs = filter_cluster(locations, map_ind, cluster_labels)
        group_colors = filter_cluster(cluster_colors, map_ind, cluster_labels)
        folium_map = get_map(group_locs, save=True, colors=group_colors)
        return render_template('map_view.html',
                               groupPager=groupPager,
                               photoPager=photoPager)


@app.route('/photo/<int:image_ind>/')
def image_view(image_ind=None):
    global groupPager
    global photoPager
    global table_group
    if image_ind >= photoPager.count:
        return render_template("404.html"), 404
    else:
        photoPager.current = image_ind
        return render_template(
            'photo_view.html',
            index=image_ind,
            photoPager=photoPager,
            groupPager=groupPager,
            data=table_group[image_ind])


@app.route('/cluster', methods=['POST', 'GET'])
def cluster():
    global cluster_labels
    global colors_dict
    global cluster_colors
    global groupPager
    cluster_labels = get_labels(locations, float(request.form['clusterdistance']), timestamps)
    colors_dict = get_label_colors(cluster_labels)
    cluster_colors = [colors_dict[i] for i in cluster_labels]
    groupPager = Pager(max(cluster_labels) + 1)
    return redirect('/')


if __name__ == '__main__':
    app.run(host='localhost', port=9750, debug=True)
