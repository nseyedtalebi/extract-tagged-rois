#Based on image export and roi export scripts that come with Omero
#This code would be much easier to understand with type annotations
#I should add some!

import omero
from omero.constants.namespaces import NSCREATED, NSOMETIFF
import omero.scripts as scripts
import omero.util.script_utils as script_utils
from omero.gateway import BlitzGateway
from omero.rtypes import rlong, rint, rstring, robject, unwrap, robject
from omero.model import RectangleI, EllipseI, LineI, PolygonI, PolylineI, \
    MaskI, LabelI, PointI
try:
    from PIL import Image  # see ticket:2597
except ImportError:
    import Image

from math import sqrt, pi
import re
import os
import glob
import zipfile
from datetime import datetime

DEFAULT_FILE_NAME = "Batch_ROI_Export.csv"
INSIGHT_POINT_LIST_RE = re.compile(r'points\[([^\]]+)\]')

# keep track of log strings.
log_strings = []


COLUMN_NAMES = ["image_id",
                "image_name",
                "roi_id",
                "shape_id",
                "type",
                "text",
                "z",
                "t",
                "channel",
                "area",
                "length",
                "points",
                "min",
                "max",
                "sum",
                "mean",
                "std_dev",
                "X",
                "Y",
                "Width",
                "Height",
                "RadiusX",
                "RadiusY",
                "X1",
                "Y1",
                "X2",
                "Y2",
                "Points"]
def log(text):
    """
    Adds the text to a list of logs. Compiled into text file at the end.
    """
    # Handle unicode
    try:
        text = text.encode('utf8')
    except UnicodeEncodeError:
        pass
    log_strings.append(str(text))

def get_roi_export_data(conn, script_params, image, units=None):
    """Get pixel data for shapes on image and returns list of dicts."""
    log("Image ID %s..." % image.id)

    # Get pixel size in SAME units for all images
    pixel_size_x = None
    pixel_size_y = None
    if units is not None:
        pixel_size_x = image.getPixelSizeX(units=units)
        pixel_size_x = pixel_size_x.getValue() if pixel_size_x else None
        pixel_size_y = image.getPixelSizeY(units=units)
        pixel_size_y = pixel_size_y.getValue() if pixel_size_y else None

    roi_service = conn.getRoiService()
    all_planes = script_params["Export_All_Planes"]
    size_c = image.getSizeC()
    # Channels index
    channels = script_params.get("Channels", [1])
    ch_indexes = []
    for ch in channels:
        if ch < 1 or ch > size_c:
            log("Channel index: %s out of range 1 - %s" % (ch, size_c))
        else:
            # User input is 1-based
            ch_indexes.append(ch - 1)

    ch_names = image.getChannelLabels()

    ch_names = [ch_name.replace(",", ".") for ch_name in ch_names]
    image_name = image.getName().replace(",", ".")

    result = roi_service.findByImage(image.getId(), None)

    rois = result.rois
    # Sort by ROI.id (same as in iviewer)
    rois.sort(key=lambda r: r.id.val)
    export_data = []

    for roi in rois:
        for shape in roi.copyShapes():
            label = unwrap(shape.getTextValue())
            # wrap label in double quotes in case it contains comma
            label = "" if label is None else '"%s"' % label.replace(",", ".")
            shape_type = shape.__class__.__name__.rstrip('I').lower()
            # If shape has no Z or T, we may go through all planes...
            the_z = unwrap(shape.theZ)
            z_indexes = [the_z]
            if the_z is None and all_planes:
                z_indexes = range(image.getSizeZ())
            # Same for T...
            the_t = unwrap(shape.theT)
            t_indexes = [the_t]
            if the_t is None and all_planes:
                t_indexes = range(image.getSizeT())

            # get pixel intensities
            for z in z_indexes:
                for t in t_indexes:
                    if z is None or t is None:
                        stats = None
                    else:
                        stats = roi_service.getShapeStatsRestricted(
                            [shape.id.val], z, t, ch_indexes)
                    for c, ch_index in enumerate(ch_indexes):
                        row_data = {
                            "image_id": image.getId(),
                            "image_name": '"%s"' % image_name,
                            "roi_id": roi.id.val,
                            "shape_id": shape.id.val,
                            "type": shape_type,
                            "text": label,
                            "z": z + 1 if z is not None else "",
                            "t": t + 1 if t is not None else "",
                            "channel": ch_names[ch_index],
                            "points": stats[0].pointsCount[c] if stats else "",
                            "min": stats[0].min[c] if stats else "",
                            "max": stats[0].max[c] if stats else "",
                            "sum": stats[0].sum[c] if stats else "",
                            "mean": stats[0].mean[c] if stats else "",
                            "std_dev": stats[0].stdDev[c] if stats else ""
                        }
                        add_shape_coords(shape, row_data,
                                         pixel_size_x, pixel_size_y)
                        export_data.append(row_data)

    return export_data

def add_shape_coords(shape, row_data, pixel_size_x, pixel_size_y):
    """Add shape coordinates and length or area to the row_data dict."""
    if shape.getTextValue():
        row_data['Text'] = shape.getTextValue().getValue()
    if isinstance(shape, (RectangleI, EllipseI, PointI, LabelI, MaskI)):
        row_data['X'] = shape.getX().getValue()
        row_data['Y'] = shape.getY().getValue()
    if isinstance(shape, (RectangleI, MaskI)):
        row_data['Width'] = shape.getWidth().getValue()
        row_data['Height'] = shape.getHeight().getValue()
        row_data['area'] = row_data['Width'] * row_data['Height']
    if isinstance(shape, EllipseI):
        row_data['RadiusX'] = shape.getRadiusX().getValue()
        row_data['RadiusY'] = shape.getRadiusY().getValue()
        row_data['area'] = pi * row_data['RadiusX'] * row_data['RadiusY']
    if isinstance(shape, LineI):
        row_data['X1'] = shape.getX1().getValue()
        row_data['X2'] = shape.getX2().getValue()
        row_data['Y1'] = shape.getY1().getValue()
        row_data['Y2'] = shape.getY2().getValue()
        dx = (row_data['X1'] - row_data['X2'])
        dx = dx if pixel_size_x is None else dx * pixel_size_x
        dy = (row_data['Y1'] - row_data['Y2'])
        dy = dy if pixel_size_y is None else dy * pixel_size_y
        row_data['length'] = sqrt((dx * dx) + (dy * dy))
    if isinstance(shape, (PolygonI, PolylineI)):
        point_list = shape.getPoints().getValue()
        match = INSIGHT_POINT_LIST_RE.search(point_list)
        if match is not None:
            point_list = match.group(1)
        row_data['Points'] = '"%s"' % point_list
    if isinstance(shape, PolylineI):
        coords = point_list.split(" ")
        coords = [[float(x.strip(", ")) for x in coord.split(",", 1)]
                  for coord in coords]
        lengths = []
        for i in range(len(coords)-1):
            dx = (coords[i][0] - coords[i + 1][0])
            dy = (coords[i][1] - coords[i + 1][1])
            dx = dx if pixel_size_x is None else dx * pixel_size_x
            dy = dy if pixel_size_y is None else dy * pixel_size_y
            lengths.append(sqrt((dx * dx) + (dy * dy)))
        row_data['length'] = sum(lengths)
    if isinstance(shape, PolygonI):
        # https://www.mathopenref.com/coordpolygonarea.html
        coords = point_list.split(" ")
        coords = [[float(x.strip(", ")) for x in coord.split(",", 1)]
                  for coord in coords]
        total = 0
        for c in range(len(coords)):
            coord = coords[c]
            next_coord = coords[(c + 1) % len(coords)]
            total += (coord[0] * next_coord[1]) - (next_coord[0] * coord[1])
        row_data['area'] = abs(0.5 * total)
    if 'area' in row_data and pixel_size_x and pixel_size_y:
        row_data['area'] = row_data['area'] * pixel_size_x * pixel_size_y


def write_csv(conn, export_data, script_params, units_symbol):
    """Write the list of data to a CSV file and create a file annotation."""
    file_name = script_params.get("File_Name", "")
    if len(file_name) == 0:
        file_name = DEFAULT_FILE_NAME
    if not file_name.endswith(".csv"):
        file_name += ".csv"

    csv_header = ",".join(COLUMN_NAMES)
    if units_symbol is None:
        units_symbol = "pixels"
    csv_header = csv_header.replace(",length,", ",length (%s)," % units_symbol)
    csv_header = csv_header.replace(",area,", ",area (%s)," % units_symbol)
    csv_rows = [csv_header]

    for row in export_data:
        cells = [str(row.get(name, "")) for name in COLUMN_NAMES]
        csv_rows.append(",".join(cells))

    with open(file_name, 'w') as csv_file:
        csv_file.write("\n".join(csv_rows))

    return conn.createFileAnnfromLocalFile(file_name, mimetype="text/csv")


def link_annotation(objects, file_ann):
    """Link the File Annotation to each object."""
    for o in objects:
        if o.canAnnotate():
            o.linkAnnotation(file_ann)


def batch_roi_export(conn, script_params):
    """Main entry point. Get images, process them and return result."""
    images = []

    if script_params['Data_Type'] == "Image":
        images = list(conn.getObjects("Image", script_params['IDs']))
    else:
        for dataset in conn.getObjects("Dataset", script_params['IDs']):
            images.extend(list(dataset.listChildren()))

    log("Processing %s images..." % len(images))
    if len(images) == 0:
        return None

    # Find units for length. If any images have NO pixel size, use 'pixels'
    # since we can't convert
    any_none = False
    for i in images:
        if i.getPixelSizeX() is None:
            any_none = True
    pixel_size_x = images[0].getPixelSizeX(units=True)
    units = None if any_none else pixel_size_x.getUnit()
    symbol = None if any_none else pixel_size_x.getSymbol()

    # build a list of dicts.
    export_data = []
    for image in images:
        export_data.extend(get_export_data(conn, script_params, image, units))

    # Write to csv
    file_ann = write_csv(conn, export_data, script_params, symbol)
    if script_params['Data_Type'] == "Dataset":
        datasets = conn.getObjects("Dataset", script_params['IDs'])
        link_annotation(datasets, file_ann)
    else:
        link_annotation(images, file_ann)
    message = "Exported %s shapes" % len(export_data)
    return file_ann, message

def get_export_data(conn, script_params, image, units=None):
    """Get pixel data for shapes on image and returns list of dicts."""
    log("Image ID %s..." % image.id)

    # Get pixel size in SAME units for all images
    pixel_size_x = None
    pixel_size_y = None
    if units is not None:
        pixel_size_x = image.getPixelSizeX(units=units)
        pixel_size_x = pixel_size_x.getValue() if pixel_size_x else None
        pixel_size_y = image.getPixelSizeY(units=units)
        pixel_size_y = pixel_size_y.getValue() if pixel_size_y else None

    roi_service = conn.getRoiService()
    all_planes = script_params["Export_All_Planes"]
    size_c = image.getSizeC()
    # Channels index
    channels = script_params.get("Channels", [1])
    ch_indexes = []
    for ch in channels:
        if ch < 1 or ch > size_c:
            log("Channel index: %s out of range 1 - %s" % (ch, size_c))
        else:
            # User input is 1-based
            ch_indexes.append(ch - 1)

    ch_names = image.getChannelLabels()

    ch_names = [ch_name.replace(",", ".") for ch_name in ch_names]
    image_name = image.getName().replace(",", ".")

    result = roi_service.findByImage(image.getId(), None)

    rois = result.rois
    # Sort by ROI.id (same as in iviewer)
    rois.sort(key=lambda r: r.id.val)
    export_data = []

    for roi in rois:
        for shape in roi.copyShapes():
            label = unwrap(shape.getTextValue())
            # wrap label in double quotes in case it contains comma
            label = "" if label is None else '"%s"' % label.replace(",", ".")
            shape_type = shape.__class__.__name__.rstrip('I').lower()
            # If shape has no Z or T, we may go through all planes...
            the_z = unwrap(shape.theZ)
            z_indexes = [the_z]
            if the_z is None and all_planes:
                z_indexes = range(image.getSizeZ())
            # Same for T...
            the_t = unwrap(shape.theT)
            t_indexes = [the_t]
            if the_t is None and all_planes:
                t_indexes = range(image.getSizeT())

            # get pixel intensities
            for z in z_indexes:
                for t in t_indexes:
                    if z is None or t is None:
                        stats = None
                    else:
                        stats = roi_service.getShapeStatsRestricted(
                            [shape.id.val], z, t, ch_indexes)
                    for c, ch_index in enumerate(ch_indexes):
                        row_data = {
                            "image_id": image.getId(),
                            "image_name": '"%s"' % image_name,
                            "roi_id": roi.id.val,
                            "shape_id": shape.id.val,
                            "type": shape_type,
                            "text": label,
                            "z": z + 1 if z is not None else "",
                            "t": t + 1 if t is not None else "",
                            "channel": ch_names[ch_index],
                            "points": stats[0].pointsCount[c] if stats else "",
                            "min": stats[0].min[c] if stats else "",
                            "max": stats[0].max[c] if stats else "",
                            "sum": stats[0].sum[c] if stats else "",
                            "mean": stats[0].mean[c] if stats else "",
                            "std_dev": stats[0].stdDev[c] if stats else ""
                        }
                        add_shape_coords(shape, row_data,
                                         pixel_size_x, pixel_size_y)
                        export_data.append(row_data)

    return export_data


def add_shape_coords(shape, row_data, pixel_size_x, pixel_size_y):
    """Add shape coordinates and length or area to the row_data dict."""
    if shape.getTextValue():
        row_data['Text'] = shape.getTextValue().getValue()
    if isinstance(shape, (RectangleI, EllipseI, PointI, LabelI, MaskI)):
        row_data['X'] = shape.getX().getValue()
        row_data['Y'] = shape.getY().getValue()
    if isinstance(shape, (RectangleI, MaskI)):
        row_data['Width'] = shape.getWidth().getValue()
        row_data['Height'] = shape.getHeight().getValue()
        row_data['area'] = row_data['Width'] * row_data['Height']
    if isinstance(shape, EllipseI):
        row_data['RadiusX'] = shape.getRadiusX().getValue()
        row_data['RadiusY'] = shape.getRadiusY().getValue()
        row_data['area'] = pi * row_data['RadiusX'] * row_data['RadiusY']
    if isinstance(shape, LineI):
        row_data['X1'] = shape.getX1().getValue()
        row_data['X2'] = shape.getX2().getValue()
        row_data['Y1'] = shape.getY1().getValue()
        row_data['Y2'] = shape.getY2().getValue()
        dx = (row_data['X1'] - row_data['X2'])
        dx = dx if pixel_size_x is None else dx * pixel_size_x
        dy = (row_data['Y1'] - row_data['Y2'])
        dy = dy if pixel_size_y is None else dy * pixel_size_y
        row_data['length'] = sqrt((dx * dx) + (dy * dy))
    if isinstance(shape, (PolygonI, PolylineI)):
        point_list = shape.getPoints().getValue()
        match = INSIGHT_POINT_LIST_RE.search(point_list)
        if match is not None:
            point_list = match.group(1)
        row_data['Points'] = '"%s"' % point_list
    if isinstance(shape, PolylineI):
        coords = point_list.split(" ")
        coords = [[float(x.strip(", ")) for x in coord.split(",", 1)]
                  for coord in coords]
        lengths = []
        for i in range(len(coords)-1):
            dx = (coords[i][0] - coords[i + 1][0])
            dy = (coords[i][1] - coords[i + 1][1])
            dx = dx if pixel_size_x is None else dx * pixel_size_x
            dy = dy if pixel_size_y is None else dy * pixel_size_y
            lengths.append(sqrt((dx * dx) + (dy * dy)))
        row_data['length'] = sum(lengths)
    if isinstance(shape, PolygonI):
        # https://www.mathopenref.com/coordpolygonarea.html
        coords = point_list.split(" ")
        coords = [[float(x.strip(", ")) for x in coord.split(",", 1)]
                  for coord in coords]
        total = 0
        for c in range(len(coords)):
            coord = coords[c]
            next_coord = coords[(c + 1) % len(coords)]
            total += (coord[0] * next_coord[1]) - (next_coord[0] * coord[1])
        row_data['area'] = abs(0.5 * total)
    if 'area' in row_data and pixel_size_x and pixel_size_y:
        row_data['area'] = row_data['area'] * pixel_size_x * pixel_size_y


def link_annotation(objects, file_ann):
    """Link the File Annotation to each object."""
    for o in objects:
        if o.canAnnotate():
            o.linkAnnotation(file_ann)


def compress(target, base):
    """
    Creates a ZIP recursively from a given base directory.

    @param target:      Name of the zip file we want to write E.g.
                        "folder.zip"
    @param base:        Name of folder that we want to zip up E.g. "folder"
    """
    zip_file = zipfile.ZipFile(target, 'w')
    try:
        files = os.path.join(base, "*")
        for name in glob.glob(files):
            zip_file.write(name, os.path.basename(name), zipfile.ZIP_DEFLATED)

    finally:
        zip_file.close()

"""NMS: The use of 'save' here may be confusing at first. It's actually calling
the .save method on a PIL image object. Omero server manages the IO ops called
within scripts, so even files generated by e.g. the standard Python IO stuff
are managed by Omero-server without the programmer having to worry about freeing
up temporary files after use. In other words, the Python interpreter is "inside"
of Omero-server, which appears like an OS as far as Python's concerned.

Not certain I understand it yet.
"""
def save_plane(image, format, c_name, z_range, project_z, t=0, channel=None,
               greyscale=False, zoom_percent=None, folder_name=None):
    """
    Renders and saves an image to disk.

    @param image:           The image to render
    @param format:          The format to save as
    @param c_name:          The name to use
    @param z_range:         Tuple of (zIndex,) OR (zStart, zStop) for
                            projection
    @param t:               T index
    @param channel:         Active channel index. If None, use current
                            rendering settings
    @param greyscale:       If true, all visible channels will be
                            greyscale
    @param zoom_percent:    Resize image by this percent if specified
    @param folder_name:     Indicate where to save the plane
    """

    original_name = image.getName()
    log("")
    log("save_plane..")
    log("channel: %s" % c_name)
    log("z: %s" % z_range)
    log("t: %s" % t)

    # if channel == None: use current rendering settings
    if channel is not None:
        image.setActiveChannels([channel+1])    # use 1-based Channel indices
        if greyscale:
            image.setGreyscaleRenderingModel()
        else:
            image.setColorRenderingModel()
    if project_z:
        # imageWrapper only supports projection of full Z range (can't
        # specify)
        image.setProjection('intmax')

    # All Z and T indices in this script are 1-based, but this method uses
    # 0-based.
    #NMS: renderImage is somewhere in the Blitz Gateway wrappers
    #See https://downloads.openmicroscopy.org/omero/5.5.1/api/python/omero/omero.gateway.html
    #'plane' is a PIL image object, as described in the docs at the lnk above
    plane = image.renderImage(z_range[0]-1, t-1)
    if zoom_percent:
        w, h = plane.size
        fraction = (float(zoom_percent) / 100)
        plane = plane.resize((int(w * fraction), int(h * fraction)),
                             Image.ANTIALIAS)

    if format == "PNG":
        img_name = make_image_name(
            original_name, c_name, z_range, t, "png", folder_name)
        log("Saving image: %s" % img_name)
        plane.save(img_name, "PNG")
    elif format == 'TIFF':
        img_name = make_image_name(
            original_name, c_name, z_range, t, "tiff", folder_name)
        log("Saving image: %s" % img_name)
        plane.save(img_name, 'TIFF')
    else:
        img_name = make_image_name(
            original_name, c_name, z_range, t, "jpg", folder_name)
        log("Saving image: %s" % img_name)
        plane.save(img_name)


def make_image_name(original_name, c_name, z_range, t, extension, folder_name):
    """
    Produces the name for the saved image.
    E.g. imported/myImage.dv -> myImage_DAPI_z13_t01.png
    """
    name = os.path.basename(original_name)
    # name = name.rsplit(".",1)[0]  # remove extension
    if len(z_range) == 2:
        z = "%02d-%02d" % (z_range[0], z_range[1])
    else:
        z = "%02d" % z_range[0]
    img_name = "%s_%s_z%s_t%02d.%s" % (name, c_name, z, t, extension)
    if folder_name is not None:
        img_name = os.path.join(folder_name, img_name)
    # check we don't overwrite existing file
    i = 1
    name = img_name[:-(len(extension)+1)]
    while os.path.exists(img_name):
        img_name = "%s_(%d).%s" % (name, i, extension)
        i += 1
    return img_name


def save_as_ome_tiff(conn, image, folder_name=None):
    """
    Saves the image as an ome.tif in the specified folder
    """

    extension = "ome.tif"
    name = os.path.basename(image.getName())
    img_name = "%s.%s" % (name, extension)
    if folder_name is not None:
        img_name = os.path.join(folder_name, img_name)
    # check we don't overwrite existing file
    i = 1
    path_name = img_name[:-(len(extension)+1)]
    while os.path.exists(img_name):
        img_name = "%s_(%d).%s" % (path_name, i, extension)
        i += 1

    log("  Saving file as: %s" % img_name)
    file_size, block_gen = image.exportOmeTiff(bufsize=65536)
    with open(str(img_name), "wb") as f:
        for piece in block_gen:
            f.write(piece)


def save_planes_for_image(conn, image, size_c, split_cs, merged_cs,
                          channel_names=None, z_range=None, t_range=None,
                          greyscale=False, zoom_percent=None, project_z=False,
                          format="PNG", folder_name=None):
    """
    Saves all the required planes for a single image, either as individual
    planes or projection.

    @param renderingEngine:     Rendering Engine, NOT initialised.
    @param queryService:        OMERO query service
    @param imageId:             Image ID
    @param zRange:              Tuple: (zStart, zStop). If None, use default
                                Zindex
    @param tRange:              Tuple: (tStart, tStop). If None, use default
                                Tindex
    @param greyscale:           If true, all visible channels will be
                                greyscale
    @param zoomPercent:         Resize image by this percent if specified.
    @param projectZ:            If true, project over Z range.
    """

    channels = []
    if merged_cs:
        # render merged first with current rendering settings
        channels.append(None)
    if split_cs:
        for i in range(size_c):
            channels.append(i)

    # set up rendering engine with the pixels
    """
    renderingEngine.lookupPixels(pixelsId)
    if not renderingEngine.lookupRenderingDef(pixelsId):
        renderingEngine.resetDefaults()
    if not renderingEngine.lookupRenderingDef(pixelsId):
        raise "Failed to lookup Rendering Def"
    renderingEngine.load()
    """

    if t_range is None:
        # use 1-based indices throughout script
        t_indexes = [image.getDefaultT()+1]
    else:
        if len(t_range) > 1:
            t_indexes = range(t_range[0], t_range[1])
        else:
            t_indexes = [t_range[0]]

    c_name = 'merged'
    for c in channels:
        if c is not None:
            g_scale = greyscale
            if c < len(channel_names):
                c_name = channel_names[c].replace(" ", "_")
            else:
                c_name = "c%02d" % c
        else:
            # if we're rendering 'merged' image - don't want grey!
            g_scale = False
        for t in t_indexes:
            if z_range is None:
                default_z = image.getDefaultZ()+1
                save_plane(image, format, c_name, (default_z,), project_z, t,
                           c, g_scale, zoom_percent, folder_name)
            elif project_z:
                save_plane(image, format, c_name, z_range, project_z, t, c,
                           g_scale, zoom_percent, folder_name)
            else:
                if len(z_range) > 1:
                    for z in range(z_range[0], z_range[1]):
                        save_plane(image, format, c_name, (z,), project_z, t,
                                   c, g_scale, zoom_percent, folder_name)
                else:
                    save_plane(image, format, c_name, z_range, project_z, t,
                               c, g_scale, zoom_percent, folder_name)


def batch_image_export(conn, script_params):

    # for params with default values, we can get the value directly
    split_cs = script_params["Export_Individual_Channels"]
    merged_cs = script_params["Export_Merged_Image"]
    greyscale = script_params["Individual_Channels_Grey"]
    data_type = script_params["Data_Type"]
    folder_name = script_params["Folder_Name"]
    folder_name = os.path.basename(folder_name)
    format = script_params["Format"]
    project_z = "Choose_Z_Section" in script_params and \
                script_params["Choose_Z_Section"] == 'Max projection'

    if (not split_cs) and (not merged_cs):
        log("Not chosen to save Individual Channels OR Merged Image")
        return

    # check if we have these params
    channel_names = []
    if "Channel_Names" in script_params:
        channel_names = script_params["Channel_Names"]
    zoom_percent = None
    if "Zoom" in script_params and script_params["Zoom"] != "100%":
        zoom_percent = int(script_params["Zoom"][:-1])

    # functions used below for each image.
    def get_z_range(size_z, script_params):
        z_range = None
        if "Choose_Z_Section" in script_params:
            z_choice = script_params["Choose_Z_Section"]
            # NB: all Z indices in this script are 1-based
            if z_choice == 'ALL Z planes':
                z_range = (1, size_z+1)
            elif "OR_specify_Z_index" in script_params:
                z_index = script_params["OR_specify_Z_index"]
                z_index = min(z_index, size_z)
                z_range = (z_index,)
            elif "OR_specify_Z_start_AND..." in script_params and \
                    "...specify_Z_end" in script_params:
                start = script_params["OR_specify_Z_start_AND..."]
                start = min(start, size_z)
                end = script_params["...specify_Z_end"]
                end = min(end, size_z)
                # in case user got z_start and z_end mixed up
                z_start = min(start, end)
                z_end = max(start, end)
                if z_start == z_end:
                    z_range = (z_start,)
                else:
                    z_range = (z_start, z_end+1)
        return z_range

    def get_t_range(size_t, script_params):
        t_range = None
        if "Choose_T_Section" in script_params:
            t_choice = script_params["Choose_T_Section"]
            # NB: all T indices in this script are 1-based
            if t_choice == 'ALL T planes':
                t_range = (1, size_t+1)
            elif "OR_specify_T_index" in script_params:
                t_index = script_params["OR_specify_T_index"]
                t_index = min(t_index, size_t)
                t_range = (t_index,)
            elif "OR_specify_T_start_AND..." in script_params and \
                    "...specify_T_end" in script_params:
                start = script_params["OR_specify_T_start_AND..."]
                start = min(start, size_t)
                end = script_params["...specify_T_end"]
                end = min(end, size_t)
                # in case user got t_start and t_end mixed up
                t_start = min(start, end)
                t_end = max(start, end)
                if t_start == t_end:
                    t_range = (t_start,)
                else:
                    t_range = (t_start, t_end+1)
        return t_range

    # Get the images or datasets
    message = ""
    objects, log_message = script_utils.get_objects(conn, script_params)
    message += log_message
    if not objects:
        return None, message

    # Attach figure to the first image
    parent = objects[0] #NMS: Why first index? Has to do with data model?

    if data_type == 'Dataset':
        images = []
        for ds in objects:
            images.extend(list(ds.listChildren()))
        if not images:
            message += "No image found in dataset(s)"
            return None, message
    else:
        images = objects

    log("Processing %s images" % len(images))

    # somewhere to put images
    curr_dir = os.getcwd()
    exp_dir = os.path.join(curr_dir, folder_name)
    try:
        os.mkdir(exp_dir)
    except OSError:
        pass
    # max size (default 12kx12k)
    size = conn.getDownloadAsMaxSizeSetting()
    size = int(size)

    ids = []
    # do the saving to disk

    for img in images:
        log("Processing image: ID %s: %s" % (img.id, img.getName()))
        pixels = img.getPrimaryPixels()
        if (pixels.getId() in ids):
            continue
        ids.append(pixels.getId())

        if format == 'OME-TIFF':
            if img._prepareRE().requiresPixelsPyramid():
                log("  ** Can't export a 'Big' image to OME-TIFF. **")
                if len(images) == 1:
                    return None, "Can't export a 'Big' image to %s." % format
                continue
            else:
                save_as_ome_tiff(conn, img, folder_name)
        else:
            size_x = pixels.getSizeX()
            size_y = pixels.getSizeY()
            if size_x*size_y > size:
                msg = "Can't export image over %s pixels. See Omero server \
                configuration property 'omero.client.download_as.max_size \
                (https://docs.openmicroscopy.org/omero/5.5.0/sysadmins/\
                config.html#omero-client-download-as-max-size)" % size
                log("  ** %s. **" % msg)
                if len(images) == 1:
                    return None, msg
                continue
            else:
                log("Exporting image as %s: %s" % (format, img.getName()))

            log("\n----------- Saving planes from image: '%s' ------------"
                % img.getName())
            size_c = img.getSizeC()
            size_z = img.getSizeZ()
            size_t = img.getSizeT()
            z_range = get_z_range(size_z, script_params)
            t_range = get_t_range(size_t, script_params)
            log("Using:")
            if z_range is None:
                log("  Z-index: Last-viewed")
            elif len(z_range) == 1:
                log("  Z-index: %d" % z_range[0])
            else:
                log("  Z-range: %s-%s" % (z_range[0], z_range[1]-1))
            if project_z:
                log("  Z-projection: ON")
            if t_range is None:
                log("  T-index: Last-viewed")
            elif len(t_range) == 1:
                log("  T-index: %d" % t_range[0])
            else:
                log("  T-range: %s-%s" % (t_range[0], t_range[1]-1))
            log("  Format: %s" % format)
            if zoom_percent is None:
                log("  Image Zoom: 100%")
            else:
                log("  Image Zoom: %s" % zoom_percent)
            log("  Greyscale: %s" % greyscale)
            log("Channel Rendering Settings:")
            for ch in img.getChannels():
                log("  %s: %d-%d"
                    % (ch.getLabel(), ch.getWindowStart(), ch.getWindowEnd()))

            try:
                save_planes_for_image(conn, img, size_c, split_cs, merged_cs,
                                      channel_names, z_range, t_range,
                                      greyscale, zoom_percent,
                                      project_z=project_z, format=format,
                                      folder_name=folder_name)
            finally:
                # Make sure we close Rendering Engine
                img._re.close()

        # write log for exported images (not needed for ome-tiff)
        name = 'Batch_Image_Export.txt'
        with open(os.path.join(exp_dir, name), 'w') as log_file:
            for s in log_strings:
                log_file.write(s)
                log_file.write("\n")

    if len(os.listdir(exp_dir)) == 0:
        return None, "No files exported. See 'info' for more details"
    # zip everything up (unless we've only got a single ome-tiff)
    if format == 'OME-TIFF' and len(os.listdir(exp_dir)) == 1:
        ometiff_ids = [t.id for t in parent.listAnnotations(ns=NSOMETIFF)]
        conn.deleteObjects("Annotation", ometiff_ids)
        export_file = os.path.join(folder_name, os.listdir(exp_dir)[0])
        namespace = NSOMETIFF
        output_display_name = "OME-TIFF"
        mimetype = 'image/tiff'
    else:
        export_file = "%s.zip" % folder_name
        compress(export_file, folder_name)
        mimetype = 'application/zip'
        output_display_name = "Batch export zip"
        namespace = NSCREATED + "/omero/export_scripts/Batch_Image_Export"

    file_annotation, ann_message = script_utils.create_link_file_annotation(
        conn, export_file, parent, output=output_display_name,
        namespace=namespace, mimetype=mimetype)
    message += ann_message
    return file_annotation, message


def run_script():
    data_types = [rstring('Dataset'), rstring('Image')]
    formats = [rstring('JPEG'), rstring('PNG'), rstring('TIFF'),
               rstring('OME-TIFF')]
    default_z_option = 'Default-Z (last-viewed)'
    z_choices = [rstring(default_z_option),
                 rstring('ALL Z planes'),
                 # currently ImageWrapper only allows full Z-stack projection
                 rstring('Max projection'),
                 rstring('Other (see below)')]
    default_t_option = 'Default-T (last-viewed)'
    t_choices = [rstring(default_t_option),
                 rstring('ALL T planes'),
                 rstring('Other (see below)')]
    zoom_percents = omero.rtypes.wrap(["25%", "50%", "100%", "200%",
                                       "300%", "400%"])

    client = scripts.client(
        'extract_tagged_rois.py',
        """Extract ROIs annotated with a user-selectable character. The text   \
        following the character becomes the name of a tag attached to the ROI. \
        There may be multiple tags per ROI separated by the tag delimiter. The \ 
        output is a ZIP file with images of the ROIs and a comma-delimited text\
        file containing index info. Each tag is exported as a separate row and \
        has a unique identifier. Image files are named by ROI ID, and each row \
        in the index info has a field containing the id of the corresponding   \
        ROI.""",

        scripts.String(
            "Data_Type", optional=False, grouping="1",
            description="The data you want to work with.", values=data_types,
            default="Image"),

        scripts.List(
            "IDs", optional=False, grouping="2",
            description="List of Dataset IDs or Image IDs").ofType(rlong(0)),

        scripts.Bool(
            "Export_Individual_Channels", grouping="3",
            description="Save individual channels as separate images",
            default=True),

        scripts.Bool(
            "Individual_Channels_Grey", grouping="3.1",
            description="If true, all individual channel images will be"
                        " grayscale", default=False),

        scripts.List(
            "Channel_Names", grouping="3.2",
            description="Names for saving individual channel images"),

        scripts.Bool(
            "Export_Merged_Image", grouping="4",
            description="Save merged image, using current rendering settings",
            default=True),

        scripts.String(
            "Format", grouping="8",
            description="Format to save image", values=formats,
            default='JPEG'),

        scripts.String(
            "Folder_Name", grouping="9",
            description="Name of folder (and zip file) to store images and index file",
            default='Tagged_ROI_Export'),

        scripts.String(
            "Tag_Delimiter", grouping="10", description="Tag delimiter character that indicates the beginning of each tag. All other characters are assumed to be part of a tag.",
            default="#"),

        version="4.3.0",
        authors=["William Moore", "OME Team", "Nima Seyedtalebi"],
        institutions=["University of Dundee", "University of Kentucky"],
        contact="ome-users@lists.openmicroscopy.org.uk",
    )

    try:
        start_time = datetime.now()
        script_params = {}
        conn = BlitzGateway(client_obj=client)
        script_params = client.getInputs(unwrap=True)
        for key, value in script_params.items():
            log("%s:%s" % (key, value))
        # call the main script - returns a file annotation wrapper
        file_annotation, message = batch_image_export(conn, script_params)
        stop_time = datetime.now()
        log("Duration: %s" % str(stop_time-start_time))
        # return this fileAnnotation to the client.
        client.setOutput("Message", rstring(message))
        if file_annotation is not None:
            client.setOutput("File_Annotation",
                             robject(file_annotation._obj))
    finally:
        client.closeSession()

if __name__ == "__main__":
    run_script()