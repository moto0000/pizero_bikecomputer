import os
import sqlite3
import datetime
import shutil
import re
import xml.etree.ElementTree as ET
from math import factorial

import numpy as np

import importlib
EXTLIB_POLYLINE_DECODER = None
try:
  EXTLIB_POLYLINE_DECODER = importlib.import_module("extlib.decode-google-maps-polyline.polyline_decoder")
except:
  pass


class LoaderTcx():
  
  config = None
  sensor = None

  #for course
  info = {}
  distance = np.array([])
  altitude = np.array([])
  latitude = np.array([])
  longitude = np.array([])
  points_diff = np.array([]) #for course distance

  azimuth = np.array([])
  slope = np.array([])
  slope_smoothing = np.array([])
  colored_altitude = np.array([])

  #for course points
  point_name = np.array([])
  point_latitude = np.array([])
  point_longitude = np.array([])
  point_type = np.array([])
  point_notes = np.array([])
  point_distance = np.array([])

  def __init__(self, config, sensor):
    print("\tlogger_core : init...")
    super().__init__()
    self.config = config
    self.sensor = sensor

  def reset(self):
    
    #for course
    self.info = {}
    #raw data
    self.distance = np.array([])
    self.altitude = np.array([])
    self.latitude = np.array([])
    self.longitude = np.array([])
    #processed variables
    self.azimuth = np.array([])
    self.slope = np.array([])
    self.slope_smoothing = np.array([])
    self.colored_altitude = np.array([])
    self.points_diff = np.array([])

    #for course points
    self.point_name = np.array([])
    self.point_latitude = np.array([])
    self.point_longitude = np.array([])
    self.point_type = np.array([])
    self.point_notes = np.array([])
    self.point_distance = np.array([])
    self.point_altitude = np.array([])

    #for external modules
    self.sensor.sensor_gps.reset_course_index()

  def load(self):
    self.reset()
    self.read_tcx()
    #self.get_google_route()
    self.downsample()
    self.calc_slope_smoothing()
    self.modify_course_points()

  def read_tcx(self):
    if not os.path.exists(self.config.G_COURSE_FILE):
      return
    print("loading", self.config.G_COURSE_FILE)
    
    t = datetime.datetime.utcnow()

    #read with regex
    pattern = {
      "name": re.compile(r'<Name>(?P<text>[\s\S]*?)</Name>'),
      "distance_meters": re.compile(r'<DistanceMeters>(?P<text>[\s\S]*?)</DistanceMeters>'),
      "track": re.compile(r'<Track>(?P<text>[\s\S]*?)</Track>'),
      "latitude": re.compile(r'<LatitudeDegrees>(?P<text>[^<]*)</LatitudeDegrees>'),
      "longitude": re.compile(r'<LongitudeDegrees>(?P<text>[^<]*)</LongitudeDegrees>'),
      "altitude": re.compile(r'<AltitudeMeters>(?P<text>[^<]*)</AltitudeMeters>'),
      "distance": re.compile(r'<DistanceMeters>(?P<text>[^<]*)</DistanceMeters>'),
      "course_point": re.compile(r'<CoursePoint>(?P<text>[\s\S]+)</CoursePoint>'),
      "course_name": re.compile(r'<Name>(?P<text>[^<]*)</Name>'),
      "course_point_type": re.compile(r'<PointType>(?P<text>[^<]*)</PointType>'),
      "course_notes": re.compile(r'<Notes>(?P<text>[^<]*)</Notes>'),
    }

    with open(self.config.G_COURSE_FILE, 'r', encoding="utf-8_sig") as f:
      tcx = f.read()

      match_name = pattern["name"].search(tcx)
      if match_name:
        self.info['Name'] = match_name.group('text').strip()
      
      match_distance_meter = pattern["distance_meters"].search(tcx)
      if match_distance_meter:
        self.info['DistanceMeters'] = round(float(match_distance_meter.group('text').strip())/1000,1)

      match_track = pattern["track"].search(tcx)
      if match_track:
        track = match_track.group('text')
        self.latitude = np.array([float(m.group('text').strip()) for m in pattern["latitude"].finditer(track)])
        self.longitude = np.array([float(m.group('text').strip()) for m in pattern["longitude"].finditer(track)])
        self.altitude = np.array([float(m.group('text').strip()) for m in pattern["altitude"].finditer(track)])
        self.distance = np.array([float(m.group('text').strip()) for m in pattern["distance"].finditer(track)])
      
      match_course = pattern["course_point"].search(tcx)
      if match_course:
        course_point = match_course.group('text')
        self.point_name = [m.group('text').strip() for m in pattern["course_name"].finditer(course_point)]
        self.point_latitude = np.array([float(m.group('text').strip()) for m in pattern["latitude"].finditer(course_point)])
        self.point_longitude = np.array([float(m.group('text').strip()) for m in pattern["longitude"].finditer(course_point)])
        self.point_type = [m.group('text').strip() for m in pattern["course_point_type"].finditer(course_point)]
        self.point_notes = [m.group('text').strip() for m in pattern["course_notes"].finditer(course_point)]
    
    print("\tlogger_core : load_course : read loop block(regex): ", (datetime.datetime.utcnow()-t).total_seconds(), "sec")

    check_course = False
    if not (len(self.latitude) == len(self.longitude) == len(self.altitude) == len(self.distance)):
      print("ERROR parse course")
      check_course = True
    if not (len(self.point_name) == len(self.point_latitude) == len(self.point_longitude) == len(self.point_type)):
      print("ERROR parse course point")
      check_course = True
    if check_course:
      self.read_from_xml()
  
  def get_google_route(self):
    json_routes = self.config.get_google_routes()
    if EXTLIB_POLYLINE_DECODER == None or json_routes == None or json_routes["status"] != "OK":
      return
    
    self.info['Name'] = "Google routes"
    self.info['DistanceMeters'] = round(json_routes["routes"][0]["legs"][0]["distance"]["value"]/1000,1)

    points = np.array(EXTLIB_POLYLINE_DECODER.decode_polyline(json_routes["routes"][0]["overview_polyline"]["points"]))
    points_detail = []
    self.point_name = []
    self.point_latitude = []
    self.point_longitude = []
    self.point_distance = []
    self.point_type = []
    self.point_notes = []

    dist = 0
    pattern = {
      "html_remove_1": re.compile(r'\/?\</?\w+\/?\>'),
      "html_remove_2":re.compile(r'\<\S+\>'),
    }
    for step in json_routes["routes"][0]["legs"][0]["steps"]:
      points_detail.extend(EXTLIB_POLYLINE_DECODER.decode_polyline(step["polyline"]["points"]))
      self.point_latitude.append(step["start_location"]["lat"])
      self.point_longitude.append(step["start_location"]["lng"])
      dist += step["distance"]["value"]/1000
      self.point_distance.append(dist)
      if "maneuver" in step:
        self.point_type.append(step["maneuver"])
      else:
        self.point_type.append("")
      text = (re.subn(pattern["html_remove_1"],"", step["html_instructions"])[0]).replace(" ","").replace("&nbsp;", "")
      text = re.subn(pattern["html_remove_2"],"",text)[0]
      self.point_name.append(text)
    points_detail = np.array(points_detail)
    #print(self.point_name)

    self.latitude = np.array(points_detail)[:,0]
    self.longitude = np.array(points_detail)[:,1]
    self.point_latitude = np.array(self.point_latitude)
    self.point_longitude = np.array(self.point_longitude)
    self.point_distance = np.array(self.point_distance)

  def downsample(self):
    len_lat = len(self.latitude)
    len_lon = len(self.longitude)
    len_alt = len(self.altitude)
    len_dist = len(self.distance)

    #empty check
    if len_lat == 0 and len_lon == 0 and len_alt == 0 and len_dist == 0:
      return

    t = datetime.datetime.utcnow()

    cond = np.array([])
    if len_lat == len_lon:
      #ame points are delete
      points_cond = np.where(np.diff(self.latitude) != 0, True, False) | np.where(np.diff(self.longitude) != 0, True, False)
      if len_lat == len_dist:
        #close points are delete
        dist_cond = np.where(np.diff(self.distance) >= 1, True, False)
        cond = np.insert(dist_cond & points_cond, 0, True)
      else:
        cond = np.insert(points_cond, 0, True)

    self.latitude = self.latitude[cond]
    self.longitude = self.longitude[cond]
    if len_dist > 0:
      self.distance = self.distance[cond]/1000 #[km]
    if len_alt > 0:
      self.altitude = self.altitude[cond] #[m]
    #print("all: {}, downsampling(1st):{}".format(len_lat, np.sum(cond)))
    self.azimuth = self.config.calc_azimuth(self.latitude, self.longitude)
    if len_dist > 0 and len_alt > 0:
      self.slope = 100*np.diff(self.altitude)/np.diff(1000*self.distance)
    
    #diffs(temporary)
    azimuth_diff = np.diff(self.azimuth)
    cond = np.insert(np.where(abs(azimuth_diff) <= 3, False, True), 0, True)
    if len_alt > 0:
      alt_diff = np.diff(self.altitude)
      alt_cond = np.where(abs(alt_diff) < 1.0, False, True)
      if len_dist > 0:
        slope_diff = np.diff(self.slope)
        slope_cond = np.insert(np.where(abs(slope_diff) <= 2, False, True), 0, True)
        cond = cond | (alt_cond & slope_cond)
      else:
        cond = cond | alt_cond
    cond = np.insert(cond, 0, True)
    cond[-1] = True

    while np.sum(cond) != len(cond):
      self.latitude = self.latitude[cond]
      self.longitude = self.longitude[cond]
      self.points_diff = np.array([np.diff(self.longitude), np.diff(self.latitude)])
      self.points_diff_sum_of_squares = self.points_diff[0]**2 + self.points_diff[1]**2
      points_cond = np.where(self.points_diff_sum_of_squares == 0.0, False, True)
      if len_alt > 0:
        self.altitude = self.altitude[cond]
      if len_dist > 0:
        self.distance = self.distance[cond]
        dist_cond = np.where(np.diff(self.distance) == 0.0, False, True)
        cond = np.insert(dist_cond & points_cond, 0, True)
      else:
        cond = np.insert(points_cond, 0, True)

    self.azimuth = np.insert(self.config.calc_azimuth(self.latitude, self.longitude), 0, 0)
    self.points_diff_dist = np.sqrt(self.points_diff_sum_of_squares) #for sensor_gps

    if len_dist == 0:
      self.distance = self.config.get_dist_on_earth_array(
        self.longitude[0:-1],
        self.latitude[0:-1],
        self.longitude[1:], 
        self.latitude[1:],
      )/1000
      self.distance = np.insert(self.distance, 0, 0)
    dist_diff = 1000 * np.diff(self.distance) #[m]

    if len_alt > 0:
      self.altitude = self.savitzky_golay(self.altitude, 53, 3)
      self.slope = np.insert(100*np.diff(self.altitude)/dist_diff, 0, 0)
      #experimental code
      #np.savetxt('log/course_altitude.csv', self.altitude, fmt='%.7f')
      #alt_d1 =  self.savitzky_golay(np.gradient(self.altitude, self.distance*1000)*100, 53, 3)
      #alt_d2 =  np.gradient(alt_d1, self.distance*1000)
      #alt_d3 =  np.gradient(alt_d2, self.distance*1000)
      #np.savetxt('log/course_altitude_d1.csv', alt_d1, fmt='%.7f')
      #np.savetxt('log/course_altitude_d2.csv', alt_d2, fmt='%.7f')
      #np.savetxt('log/course_altitude_d3.csv', alt_d3, fmt='%.7f')
    
    #update G_GPS_ON_ROUTE_CUTOFF from course

    diff_dist_max = int(np.argmax(dist_diff))*5/1000 #[m->km]
    #self.config.G_GPS_ON_ROUTE_CUTOFF = diff_dist_max #[m]
    if diff_dist_max > self.config.G_GPS_SEARCH_RANGE: #[km]
      self.config.G_GPS_SEARCH_RANGE = diff_dist_max
    #print("G_GPS_ON_ROUTE_CUTOFF[m]:", self.config.G_GPS_ON_ROUTE_CUTOFF)
    #print("G_GPS_SEARCH_RANGE[km]:", self.config.G_GPS_SEARCH_RANGE)

    #print("downsampling(2nd):{}".format(len(self.latitude)))

    print("\tlogger_core : load_course : read loop block(downsampling): ", (datetime.datetime.utcnow()-t).total_seconds(), "sec")

  def calc_slope_smoothing(self):
    #make slope_smoothing by distance (self.config.G_SLOPE_WINDOW_DISTANCE)
    self.colored_altitude = np.full((len(self.distance), 3),self.config.G_SLOPE_COLOR[0])

    if len(self.distance) == 0 or len(self.altitude) == 0:
      return
    
    t = datetime.datetime.utcnow()
    course_n = len(self.distance)

    ##### obsolete #####
    #print(np.round(alt_diff[0:40], 1))
    #print(np.round(1000*np.diff(self.distance)[0:40]))
    #print(self.distance[0:40])
    #print(np.round(self.slope[0:40], 1))
    self.slope_smoothing = np.empty(course_n)
    alt_start = alt_end = pre_dist_slope = pre_slope_smoothing = np.nan
    first_track = True
    for i in range(course_n):
      distance = self.distance[i]*1000 #[m]
      altitude = self.altitude[i]
      
      if not first_track and distance - pre_dist_slope >= self.config.G_SLOPE_WINDOW_DISTANCE:
        alt_end = altitude
        slope_smoothing = 100*(alt_end - alt_start)/ (distance - pre_dist_slope)
        
        #reset
        pre_dist_slope = distance
        alt_start = alt_end
        #last one is first value of filling slope_smoothing
        pre_slope_smoothing = slope_smoothing
      else:
        slope_smoothing = np.nan
      
      if first_track:
        first_track = False
        alt_start = altitude
        alt_end = altitude
        pre_dist_slope = distance

      self.slope_smoothing[i] = slope_smoothing

    if len(self.slope_smoothing) > 0 and np.isnan(self.slope_smoothing[-1]):
      self.slope_smoothing[-1] = 100*(self.altitude[-1] - alt_start) / (self.distance[-1]*1000 - pre_dist_slope)
    print("\tlogger_core : load_course : slope_smoothing: ", (datetime.datetime.utcnow()-t).total_seconds(), "sec")
    #t = datetime.datetime.utcnow()

    #Backward fill
    #https://stackoverflow.com/questions/41190852/most-efficient-way-to-forward-fill-nan-values-in-numpy-array
    self.slope_smoothing = self.slope_smoothing.reshape([1, course_n])
    slope_mask = np.isnan(self.slope_smoothing)
    idx = np.where(~slope_mask, np.arange(slope_mask.shape[1]), slope_mask.shape[1] - 1)
    idx = np.minimum.accumulate(idx[:, ::-1], axis=1)[:, ::-1]
    self.slope_smoothing = self.slope_smoothing[np.arange(idx.shape[0])[:,None], idx]
    self.slope_smoothing = self.slope_smoothing.flatten()
    
    #print("\tlogger_core : load_course : backward fill: ", (datetime.datetime.utcnow()-t).total_seconds(), "sec")
    
    self.colored_altitude = np.full((len(self.altitude), 3),self.config.G_SLOPE_COLOR[0])
    for i in range(len(self.config.G_SLOPE_CUTOFF)):
      cond = None
      if i == 0:
        x2 = self.config.G_SLOPE_CUTOFF[i]
        cond = np.where(self.slope_smoothing <= x2, True, False)
      else:
        x1 = self.config.G_SLOPE_CUTOFF[i-1]
        x2 = self.config.G_SLOPE_CUTOFF[i]
        cond = np.where((x1 < self.slope_smoothing) & (self.slope_smoothing <= x2), True, False)
      self.colored_altitude[cond] = self.config.G_SLOPE_COLOR[i]
      
    #print("\tlogger_core : load_course : fill slope: ", (datetime.datetime.utcnow()-t).total_seconds(), "sec")
    #t = datetime.datetime.utcnow()
  
  def modify_course_points(self):
    #make route colors by slope for SimpleMapWidget, CourseProfileWidget

    t = datetime.datetime.utcnow()

    len_pnt_name = len(self.point_name)
    len_pnt_lat = len(self.point_latitude)
    len_pnt_lon = len(self.point_longitude)
    len_pnt_dist = len(self.point_distance)
    len_pnt_alt = len(self.point_altitude)
    len_pnt_type = len(self.point_type)

    #calculate course point distance
    if len_pnt_dist == 0 and len(self.distance) > 0:
      self.point_distance = np.empty(len(self.point_latitude))
    if len_pnt_alt == 0 and len(self.altitude) > 0:
      self.point_altitude = np.zeros(len(self.point_latitude))
    
    min_index = 0
    for i in range(len(self.point_latitude)):
      b_a_x = self.points_diff[0][min_index:]
      b_a_y = self.points_diff[1][min_index:]
      lon_diff = self.point_longitude[i] - self.longitude[min_index:]
      lat_diff = self.point_latitude[i] - self.latitude[min_index:]
      p_a_x = lon_diff[:-1]
      p_a_y = lat_diff[:-1]
      p_b_x = lon_diff[1:]
      p_b_y = lat_diff[1:]
      inner_p = (b_a_x*p_a_x + b_a_y*p_a_y)/self.points_diff_sum_of_squares[min_index:]
      inner_p_check = np.where((0.0 <= inner_p) & (inner_p <= 1.0), True, False)

      for j in np.where(inner_p_check == True)[0]:
        h_lon = self.longitude[min_index+j] + \
          (self.longitude[min_index+j+1]-self.longitude[min_index+j]) * inner_p[j]
        h_lat = self.latitude[min_index+j] + \
          (self.latitude[min_index+j+1]-self.latitude[min_index+j]) * inner_p[j]
        dist_diff_h = self.config.get_dist_on_earth(
          h_lon, 
          h_lat,
          self.point_longitude[i], 
          self.point_latitude[i]
          )

        if dist_diff_h < self.config.G_GPS_ON_ROUTE_CUTOFF:
          min_index = min_index+j
          break
      
      if len_pnt_dist == 0 and len(self.distance) > 0:
        self.point_distance[i] = self.distance[min_index]
      if len_pnt_alt == 0 and len(self.altitude) > 0:
        self.point_altitude[i] = self.altitude[min_index]

    #print(len(self.point_distance), len(self.point_altitude))

    len_lat = len(self.point_latitude)
    len_dist = len(self.distance)
    len_alt = len(self.altitude)
    len_pnt_dist = len(self.point_distance)
    len_pnt_alt = len(self.point_altitude)

    #add start course point
    if len_lat > 0 and len_pnt_dist > 0 and len_dist > 0 and self.point_distance[0] != 0.0:
      self.point_name.insert(0, "Start")
      self.point_latitude = np.insert(self.point_latitude, 0, self.latitude[0])
      self.point_longitude = np.insert(self.point_longitude, 0, self.longitude[0])
      self.point_type.insert(0, "")
      if len_pnt_dist > 0 and len_dist > 0:
        self.point_distance = np.insert(self.point_distance, 0, 0.0)
      if len_pnt_alt > 0 and len_alt > 0:
        self.point_altitude = np.insert(self.point_altitude, 0, self.altitude[0])
    #add end course point
    if len_lat > 0 and len_pnt_dist > 0 and len_dist > 0 and self.point_distance[-1] != self.distance[-1]:
      self.point_name.append("End")
      self.point_latitude = np.append(self.point_latitude, self.latitude[-1])
      self.point_longitude = np.append(self.point_longitude, self.longitude[-1])
      self.point_type.append("")
      if len_pnt_dist > 0 and len_dist > 0:
        self.point_distance = np.append(self.point_distance, self.distance[-1])
      if len_pnt_alt > 0 and len_alt > 0:
        self.point_altitude = np.append(self.point_altitude, self.altitude[-1])
    
    self.point_name = np.array(self.point_name)
    self.point_type = np.array(self.point_type)
    self.point_name = np.array(self.point_name)

    print("\tlogger_core : load_course : slope and course distance: ", (datetime.datetime.utcnow()-t).total_seconds(), "sec")
   
  def read_from_xml(self):
    if not os.path.exists(self.config.G_COURSE_FILE):
      return
    
    t = datetime.datetime.utcnow()
    
    self.reset()
    tree = ET.parse(self.config.G_COURSE_FILE)
    tcx_root = tree.getroot()
    
    print("\tlogger_core : read_from_xml : ET parse", (datetime.datetime.utcnow()-t).total_seconds(), "sec")
    t = datetime.datetime.utcnow()
    
    # namespace 
    NS = {'TCDv2': 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2'}
    courses = tcx_root.find('TCDv2:Courses', NS)
    course = courses.find('TCDv2:Course', NS)
    #summary
    self.info['Name'] = course.find('TCDv2:Name', NS).text
    Lap = course.find('TCDv2:Lap', NS)
    self.info['DistanceMeters'] = float(Lap.find('TCDv2:DistanceMeters', NS).text)
    #track
    track = course.find('TCDv2:Track', NS)
    track_points = track.findall('TCDv2:Trackpoint', NS)
    #coursepoint
    course_points = course.findall('TCDv2:CoursePoint', NS)
    
    print("\tlogger_core : read_from_xml : initialize", (datetime.datetime.utcnow()-t).total_seconds(), "sec")
    t = datetime.datetime.utcnow()

    TCDv2_prefix = "{"+NS['TCDv2']+"}"

    #course data
    track_points_n = len(track_points)
    self.distance = np.empty(track_points_n)
    self.altitude = np.empty(track_points_n)
    self.latitude = np.empty(track_points_n)
    self.longitude = np.empty(track_points_n)
    tmp_i = 0
    
    for tp in track_points:
      latitude = longitude = distance = altitude = None
      values = {}
      for child in tp.iter():
        values[child.tag] = child.text
      try:
        latitude = float(values[TCDv2_prefix+"LatitudeDegrees"])
        longitude = float(values[TCDv2_prefix+"LongitudeDegrees"])
        distance = float(values[TCDv2_prefix+"DistanceMeters"])
        altitude = float(values[TCDv2_prefix+"AltitudeMeters"])
      except:
        continue
      
      self.latitude[tmp_i] = latitude
      self.longitude[tmp_i] = longitude
      self.distance[tmp_i] = distance
      self.altitude[tmp_i] = altitude
      tmp_i += 1
    
    self.latitude = self.latitude[0:tmp_i]
    self.longitude = self.longitude[0:tmp_i]
    self.distance = self.distance[0:tmp_i]
    self.altitude = self.altitude[0:tmp_i]
    
    #course points
    point_name = []
    point_latitude = []
    point_longitude = []
    point_type = []
    point_notes = []

    for cp in course_points:
      name = latitude = longitude = p_type = notes = None
      #search
      for child in cp:
        if child.tag == TCDv2_prefix+"Name":
          name = child.text
        elif child.tag == TCDv2_prefix+"Position":
          for position_child in child:
            if position_child.tag == TCDv2_prefix+"LatitudeDegrees":
              latitude = float(position_child.text)
            elif position_child.tag == TCDv2_prefix+"LongitudeDegrees":
              longitude = float(position_child.text)
        elif child.tag == TCDv2_prefix+"PointType":
          p_type = child.text
        elif child.tag == TCDv2_prefix+"Notes":
          notes = child.text

      if name != None and latitude != None and longitude != None and p_type != None and notes != None:
        point_name.append(name)
        point_latitude.append(latitude)
        point_longitude.append(longitude)
        point_type.append(p_type)
        point_notes.append(notes)

    self.point_name = np.array(point_name)
    self.point_latitude = np.array(point_latitude)
    self.point_longitude = np.array(point_longitude)
    self.point_type = np.array(point_type)
    self.point_notes = np.array(point_notes)

    print("\tlogger_core : read_from_xml : read values: ", (datetime.datetime.utcnow()-t).total_seconds(), "sec")

  def savitzky_golay(self, y, window_size, order, deriv=0, rate=1):
    try:
        window_size = np.abs(np.int(window_size))
        order = np.abs(np.int(order))
    except ValueError as msg:
        raise ValueError("window_size and order have to be of type int")
    if window_size % 2 != 1 or window_size < 1:
        raise TypeError("window_size size must be a positive odd number")
    if window_size < order + 2:
        raise TypeError("window_size is too small for the polynomials order")
    order_range = range(order+1)
    half_window = (window_size -1) // 2
    # precompute coefficients
    b = np.mat([[k**i for i in order_range] for k in range(-half_window, half_window+1)])
    m = np.linalg.pinv(b).A[deriv] * rate**deriv * factorial(deriv)
    # pad the signal at the extremes with
    # values taken from the signal itself
    firstvals = y[0] - np.abs( y[1:half_window+1][::-1] - y[0] )
    lastvals = y[-1] + np.abs(y[-half_window-1:-1][::-1] - y[-1])
    y = np.concatenate((firstvals, y, lastvals))
    return np.convolve( m[::-1], y, mode='valid')

