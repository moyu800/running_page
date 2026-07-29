"""Create and maintain info about a given activity track (corresponding to one GPX file)."""

# Copyright 2016-2019 Florian Pigorsch & Contributors. All rights reserved.
# 2019-now yihong0618 Florian Pigorsch & Contributors. All rights reserved.
# Use of this source code is governed by a MIT-style
# license that can be found in the LICENSE file.

import datetime
import json
import math
import os
from collections import namedtuple

import gpxpy as mod_gpxpy
import lxml
import polyline
import s2sphere as s2
from garmin_fit_sdk import Decoder, Stream
from garmin_fit_sdk.util import FIT_EPOCH_S
from rich import print
from tcxreader.tcxreader import TCXReader

from backend.polyline_processor import filter_out

from .exceptions import TrackLoadError
from .utils import get_normalized_sport_type, parse_datetime_to_local

start_point = namedtuple("start_point", "lat lon")
run_map = namedtuple("polyline", "summary_polyline")

IGNORE_BEFORE_SAVING = os.getenv("IGNORE_BEFORE_SAVING", False)

# Garmin stores all latitude and longitude values as 32-bit integer values.
# This unit is called semicircle.
# So that gives 2^32 possible values.
# And to represent values up to 360° (or -180° to 180°), each 'degree' represents 2^32 / 360 = 11930465.
# So dividing latitude and longitude (int32) value by 11930465 will give the decimal value.
SEMICIRCLE = 11930465
RUNNING_CADENCE_MULTIPLIER = 2


class Track:
    def __init__(self):
        self.file_names = []
        self.polylines = []
        self.polyline_str = ""
        self.track_name = None
        self.start_time = None
        self.end_time = None
        self.start_time_local = None
        self.end_time_local = None
        self.length = 0
        self.special = False
        self.average_heartrate = None
        self.max_heartrate = None
        self.average_cadence = None
        self.cadence_trend = None
        self.split_paces = []
        self.split_heart_rates = []
        self.elevation_gain = None
        self.moving_dict = {}
        self.run_id = 0
        self.start_latlng = []
        self.type = "Run"
        self.subtype = None  # for fit file
        self.device = ""

    def load_gpx(self, file_name):
        """
        TODO refactor with load_tcx to one function
        """
        try:
            self.file_names = [os.path.basename(file_name)]
            # Handle empty gpx files
            # (for example, treadmill runs pulled via garmin-connect-export)
            if os.path.getsize(file_name) == 0:
                raise TrackLoadError("Empty GPX file")
            with open(file_name, "r", encoding="utf-8", errors="ignore") as file:
                self._load_gpx_data(mod_gpxpy.parse(file))
        except Exception as e:
            print(
                f"Something went wrong when loading GPX. for file {self.file_names[0]}, we just ignore this file and continue"
            )
            print(str(e))

    def load_tcx(self, file_name):
        try:
            self.file_names = [os.path.basename(file_name)]
            # Handle empty tcx files
            # (for example, treadmill runs pulled via garmin-connect-export)
            tcx = TCXReader()
            if os.path.getsize(file_name) == 0:
                raise TrackLoadError("Empty TCX file")
            self._load_tcx_data(tcx.read(file_name), file_name=file_name)
        except Exception as e:
            print(
                f"Something went wrong when loading TCX. for file {self.file_names[0]}, we just ignore this file and continue"
            )
            print(str(e))

    def load_fit(self, file_name):
        try:
            self.file_names = [os.path.basename(file_name)]
            # Handle empty fit files
            # (for example, treadmill runs pulled via garmin-connect-export)
            if os.path.getsize(file_name) == 0:
                raise TrackLoadError("Empty FIT file")
            stream = Stream.from_file(file_name)
            decoder = Decoder(stream)
            messages, errors = decoder.read(convert_datetimes_to_dates=False)
            if errors:
                print(
                    f"FIT file read fail: {errors}. The file appears to be corrupted and will be removed."
                )
                os.remove(file_name)
                return
            if (
                messages.get("session_mesgs") is None
                or messages.get("session_mesgs")[0].get("total_distance") is None
            ):
                print(
                    f"Session message or total distance is missing when loading FIT. for file {self.file_names[0]}, we just ignore this file and continue"
                )
                return
            self._load_fit_data(messages)
        except Exception as e:
            print(
                f"Something went wrong when loading FIT. for file {self.file_names[0]}, we just ignore this file and continue"
            )
            print(str(e))

    def load_from_db(self, activity):
        # use strava as file name
        self.file_names = [str(activity.run_id)]
        start_time = datetime.datetime.strptime(
            activity.start_date_local, "%Y-%m-%d %H:%M:%S"
        )
        self.start_time_local = start_time
        self.end_time = start_time + activity.elapsed_time
        self.length = float(activity.distance)
        if IGNORE_BEFORE_SAVING:
            summary_polyline = filter_out(activity.summary_polyline)
        else:
            summary_polyline = activity.summary_polyline
        polyline_data = polyline.decode(summary_polyline) if summary_polyline else []
        self.polylines = [[s2.LatLng.from_degrees(p[0], p[1]) for p in polyline_data]]
        self.run_id = activity.run_id
        self.type = get_normalized_sport_type(activity.type)
        self.subtype = activity.subtype if hasattr(activity, "subtype") else None
        # Load moving_dict from database
        self.moving_dict = {
            "distance": self.length,
            "moving_time": activity.moving_time,
            "elapsed_time": activity.elapsed_time,
            "average_speed": activity.average_speed or 0,
        }
        self.average_heartrate = (
            activity.average_heartrate
            if hasattr(activity, "average_heartrate")
            else None
        )
        self.max_heartrate = (
            activity.max_heartrate if hasattr(activity, "max_heartrate") else None
        )
        self.average_cadence = (
            activity.average_cadence if hasattr(activity, "average_cadence") else None
        )
        self.cadence_trend = (
            activity.cadence_trend if hasattr(activity, "cadence_trend") else None
        )
        self.split_paces = (
            activity.split_paces if hasattr(activity, "split_paces") else []
        )
        self.split_heart_rates = (
            activity.split_heart_rates if hasattr(activity, "split_heart_rates") else []
        )

    def bbox(self):
        """Compute the smallest rectangle that contains the entire track (border box)."""
        bbox = s2.LatLngRect()
        for line in self.polylines:
            for latlng in line:
                bbox = bbox.union(s2.LatLngRect.from_point(latlng.normalized()))
        return bbox

    @staticmethod
    def __make_run_id(time_stamp):
        return int(datetime.datetime.timestamp(time_stamp) * 1000)

    def _load_tcx_data(self, tcx, file_name):
        self.length = float(tcx.distance)
        time_values = [i.time for i in tcx.trackpoints]
        if not time_values:
            raise TrackLoadError("Track is empty.")

        self.start_time = tcx.start_time or time_values[0]
        self.end_time = tcx.end_time or time_values[-1]
        elapsed_time = tcx.duration or int(
            self.end_time.timestamp() - self.start_time.timestamp()
        )
        moving_time = self._calc_moving_time(tcx.trackpoints, 10)
        moving_time = moving_time or elapsed_time
        self.run_id = self.__make_run_id(self.start_time)
        self.average_heartrate = tcx.hr_avg
        polyline_container = []
        position_values = [(i.latitude, i.longitude) for i in tcx.trackpoints]
        if not position_values and int(self.length) == 0:
            raise Exception(
                f"This {file_name} TCX file do not contain distance and position values we ignore it"
            )
        if position_values:
            line = [s2.LatLng.from_degrees(p[0], p[1]) for p in position_values]
            self.polylines.append(line)
            polyline_container.extend([[p[0], p[1]] for p in position_values])
            self.polyline_container = polyline_container
            self.start_time_local, self.end_time_local = parse_datetime_to_local(
                self.start_time, self.end_time, polyline_container[0]
            )
            # get start point
            try:
                self.start_latlng = start_point(*polyline_container[0])
            except Exception as e:
                print(f"Error getting start point: {e}")
            self.polyline_str = polyline.encode(polyline_container)
        self.elevation_gain = tcx.ascent
        self.moving_dict = {
            "distance": self.length,
            "moving_time": datetime.timedelta(seconds=moving_time),
            "elapsed_time": datetime.timedelta(seconds=elapsed_time),
            "average_speed": self.length / moving_time if moving_time else 0,
        }

    def _calc_moving_time(self, trackpoints, seconds_threshold=10):
        moving_time = 0
        try:
            start_time = self.start_time
            for i in range(1, len(trackpoints)):
                if trackpoints[i].time - trackpoints[i - 1].time <= datetime.timedelta(
                    seconds=seconds_threshold
                ):
                    moving_time += (
                        trackpoints[i].time.timestamp() - start_time.timestamp()
                    )
                start_time = trackpoints[i].time
            return int(moving_time)
        except Exception as e:
            print(f"Error calculating moving time: {e}")
            return 0

    def _load_gpx_data(self, gpx):
        self.start_time, self.end_time = gpx.get_time_bounds()
        if self.start_time is None or self.end_time is None:
            # may be it's treadmill run, so we just use the start and end time of the extensions
            start_time_str = self._load_gpx_extensions_item(gpx, "start_time")
            end_time_str = self._load_gpx_extensions_item(gpx, "end_time")
            if start_time_str:
                self.start_time = datetime.datetime.fromisoformat(start_time_str)
            if end_time_str:
                self.end_time = datetime.datetime.fromisoformat(end_time_str)
            if self.start_time and self.end_time:
                self.start_time_local, self.end_time_local = parse_datetime_to_local(
                    self.start_time, self.end_time, None
                )
        # use timestamp as id
        self.run_id = self.__make_run_id(self.start_time)
        if self.start_time is None:
            raise TrackLoadError("Track has no start time.")
        if self.end_time is None:
            raise TrackLoadError("Track has no end time.")
        self.length = gpx.length_2d()
        moving_time = 0
        for t in gpx.tracks:
            for s in t.segments:
                moving_time += self._calc_moving_time(s.points, 10)
        if self.length == 0:
            self._load_gpx_extensions_data(gpx)
            return
        heart_rate_list = []
        cadence_list = []
        timed_points = []
        for t in gpx.tracks:
            if self.track_name is None:
                self.track_name = t.name
            if hasattr(t, "type") and t.type:
                self.type = "Run" if t.type == "running" else t.type
            for s in t.segments:
                try:
                    for p in s.points:
                        ext_dict = {}
                        if p.extensions:
                            ext_dict = {
                                lxml.etree.QName(child).localname: child.text
                                for child in p.extensions[0]
                            }
                        hr = (
                            int(ext_dict["hr"])
                            if ext_dict.get("hr") not in (None, "")
                            else None
                        )
                        cad = (
                            int(ext_dict["cad"])
                            if ext_dict.get("cad") not in (None, "")
                            else None
                        )
                        if hr:
                            heart_rate_list.append(hr)
                        if cad and cad > 0:
                            cadence_list.append(cad)
                        timed_points.append(
                            {
                                "lat": p.latitude,
                                "lon": p.longitude,
                                "time": p.time,
                                "hr": hr,
                                "cad": cad if cad and cad > 0 else None,
                            }
                        )
                except lxml.etree.XMLSyntaxError:
                    # Ignore XML syntax errors in extensions
                    # This can happen if the GPX file is malformed
                    pass

        gpx.simplify()
        polyline_container = []
        for t in gpx.tracks:
            for s in t.segments:
                line = [
                    s2.LatLng.from_degrees(p.latitude, p.longitude) for p in s.points
                ]
                self.polylines.append(line)
                polyline_container.extend([[p.latitude, p.longitude] for p in s.points])
                self.polyline_container = polyline_container
        # get start point
        try:
            self.start_latlng = start_point(*polyline_container[0])
        except Exception as e:
            print(f"Error getting start point: {e}")
        self.start_time_local, self.end_time_local = parse_datetime_to_local(
            self.start_time, self.end_time, polyline_container[0]
        )
        self.polyline_str = polyline.encode(polyline_container)
        self.average_heartrate = (
            sum(heart_rate_list) / len(heart_rate_list) if heart_rate_list else None
        )
        self.max_heartrate = max(heart_rate_list) if heart_rate_list else None
        self.average_cadence = (
            math.ceil(
                sum(cadence_list) / len(cadence_list) * RUNNING_CADENCE_MULTIPLIER
            )
            if cadence_list
            else None
        )
        (
            self.cadence_trend,
            self.split_paces,
            self.split_heart_rates,
        ) = self._build_derived_metrics_from_points(timed_points)
        self.moving_dict = self._get_moving_data(gpx, moving_time)
        self.elevation_gain = gpx.get_uphill_downhill().uphill
        self._load_gpx_extensions_data(gpx)

    def _load_gpx_extensions_item(self, gpx, item_name):
        """
        Load a specific extension item from the GPX file.
        This is used to load specific data like distance, average speed, etc.
        """
        gpx_extensions = (
            {}
            if gpx.extensions is None
            else {
                lxml.etree.QName(extension).localname: extension.text
                for extension in gpx.extensions
            }
        )
        return (
            gpx_extensions.get(item_name)
            if gpx_extensions.get(item_name) is not None
            else None
        )

    def _load_gpx_extensions_data(self, gpx):
        gpx_extensions = (
            {}
            if gpx.extensions is None
            else {
                lxml.etree.QName(extension).localname: extension.text
                for extension in gpx.extensions
            }
        )
        self.length = (
            self.length
            if gpx_extensions.get("distance") is None
            else float(gpx_extensions.get("distance"))
        )
        self.average_heartrate = (
            self.average_heartrate
            if gpx_extensions.get("average_hr") is None
            else float(gpx_extensions.get("average_hr"))
        )
        self.moving_dict["average_speed"] = (
            self.moving_dict["average_speed"]
            if gpx_extensions.get("average_speed") is None
            else float(gpx_extensions.get("average_speed"))
        )
        self.moving_dict["distance"] = (
            self.moving_dict["distance"]
            if gpx_extensions.get("distance") is None
            else float(gpx_extensions.get("distance"))
        )

        self.moving_dict["moving_time"] = (
            self.moving_dict["moving_time"]
            if gpx_extensions.get("moving_time") is None
            else datetime.timedelta(seconds=float(gpx_extensions.get("moving_time")))
        )

        self.moving_dict["elapsed_time"] = (
            self.moving_dict["elapsed_time"]
            if gpx_extensions.get("elapsed_time") is None
            else datetime.timedelta(seconds=float(gpx_extensions.get("elapsed_time")))
        )

    def _load_fit_data(self, fit: dict):
        _polylines = []
        self.polyline_container = []
        timed_points = []
        message = fit["session_mesgs"][0]
        self.start_time = datetime.datetime.fromtimestamp(
            (message["start_time"] + FIT_EPOCH_S), tz=datetime.UTC
        )
        self.run_id = self.__make_run_id(self.start_time)
        self.end_time = datetime.datetime.fromtimestamp(
            (message["start_time"] + FIT_EPOCH_S + message["total_elapsed_time"]),
            tz=datetime.UTC,
        )
        self.length = message["total_distance"]
        self.average_heartrate = (
            message["avg_heart_rate"] if "avg_heart_rate" in message else None
        )
        self.max_heartrate = (
            message["max_heart_rate"] if "max_heart_rate" in message else None
        )
        self.average_cadence = (
            math.ceil(message["avg_cadence"] * RUNNING_CADENCE_MULTIPLIER)
            if "avg_cadence" in message and message["avg_cadence"] is not None
            else None
        )
        if message["sport"].lower() == "running":
            self.type = "Run"
        else:
            self.type = message["sport"].lower()
        self.subtype = message["sub_sport"] if "sub_sport" in message else None

        self.elevation_gain = (
            message["total_ascent"] if "total_ascent" in message else None
        )
        # moving_dict
        self.moving_dict["distance"] = message["total_distance"]
        self.moving_dict["moving_time"] = datetime.timedelta(
            seconds=(
                message["total_moving_time"]
                if "total_moving_time" in message
                else message["total_timer_time"]
            )
        )
        self.moving_dict["elapsed_time"] = datetime.timedelta(
            seconds=message["total_elapsed_time"]
        )
        self.moving_dict["average_speed"] = message.get(
            "enhanced_avg_speed"
        ) or message.get("avg_speed", 0)
        for record in fit["record_mesgs"]:
            if "position_lat" in record and "position_long" in record:
                lat = record["position_lat"] / SEMICIRCLE
                lng = record["position_long"] / SEMICIRCLE
                _polylines.append(s2.LatLng.from_degrees(lat, lng))
                self.polyline_container.append([lat, lng])
                record_time = record.get("timestamp")
                if record_time is not None:
                    record_time = datetime.datetime.fromtimestamp(
                        record_time + FIT_EPOCH_S, tz=datetime.UTC
                    )
                timed_points.append(
                    {
                        "lat": lat,
                        "lon": lng,
                        "time": record_time,
                        "hr": record.get("heart_rate"),
                        "cad": (
                            record.get("cadence")
                            if record.get("cadence") not in (None, 0)
                            else None
                        ),
                    }
                )
        if self.polyline_container:
            self.start_time_local, self.end_time_local = parse_datetime_to_local(
                self.start_time, self.end_time, self.polyline_container[0]
            )
            self.start_latlng = start_point(*self.polyline_container[0])
            self.polylines.append(_polylines)
            self.polyline_str = polyline.encode(self.polyline_container)
        else:
            self.start_time_local, self.end_time_local = parse_datetime_to_local(
                self.start_time, self.end_time, None
            )
        (
            self.cadence_trend,
            self.split_paces,
            self.split_heart_rates,
        ) = self._build_derived_metrics_from_points(timed_points)

        # The FIT file created by Garmin
        if "file_id_mesgs" in fit:
            device_message = fit["file_id_mesgs"][0]
            if "manufacturer" in device_message:
                self.device = device_message["manufacturer"]
            if "garmin_product" in device_message:
                self.device += " " + device_message["garmin_product"]

    def append(self, other):
        """Append other track to self."""
        self.end_time = other.end_time
        self.length += other.length
        # TODO maybe a better way
        try:
            self.moving_dict["distance"] += other.moving_dict["distance"]
            self.moving_dict["moving_time"] += other.moving_dict["moving_time"]
            self.moving_dict["elapsed_time"] += other.moving_dict["elapsed_time"]
            self.polyline_container.extend(other.polyline_container)
            self.polyline_str = polyline.encode(self.polyline_container)
            self.moving_dict["average_speed"] = (
                self.moving_dict["distance"]
                / self.moving_dict["moving_time"].total_seconds()
            )
            self.file_names.extend(other.file_names)
            self.special = self.special or other.special
            self.average_heartrate = self.average_heartrate or other.average_heartrate
            self.elevation_gain = (
                self.elevation_gain if self.elevation_gain else 0
            ) + (other.elevation_gain if other.elevation_gain else 0)
        except Exception as e:
            print(
                f"something wrong append this {self.end_time},in files {self.file_names!s}: {e}"
            )

    @staticmethod
    def _get_moving_data(gpx, moving_time):
        moving_data = gpx.get_moving_data()
        elapsed_time = moving_data.moving_time
        moving_time = moving_time or elapsed_time
        return {
            "distance": moving_data.moving_distance,
            "moving_time": datetime.timedelta(seconds=moving_time),
            "elapsed_time": datetime.timedelta(seconds=elapsed_time),
            "average_speed": (
                moving_data.moving_distance / moving_time if moving_time else 0
            ),
        }

    @staticmethod
    def _haversine_m(lat1, lon1, lat2, lon2):
        radius = 6371000.0
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        )
        return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _build_derived_metrics_from_points(self, timed_points):
        valid_points = [
            p
            for p in timed_points
            if p.get("time") is not None
            and p.get("lat") is not None
            and p.get("lon") is not None
        ]
        if len(valid_points) < 2:
            return None, [], []

        cumulative = 0.0
        valid_points[0]["cum"] = 0.0
        for i in range(1, len(valid_points)):
            prev = valid_points[i - 1]
            curr = valid_points[i]
            cumulative += self._haversine_m(
                prev["lat"], prev["lon"], curr["lat"], curr["lon"]
            )
            curr["cum"] = cumulative

        all_cadence = [
            p["cad"] for p in valid_points if p.get("cad") is not None and p["cad"] > 0
        ]
        cadence_trend = None
        if all_cadence:
            midpoint = len(all_cadence) // 2
            first_half = sum(all_cadence[:midpoint]) / max(1, midpoint)
            second_half = sum(all_cadence[midpoint:]) / max(
                1, len(all_cadence) - midpoint
            )
            cadence_trend = {
                "first_half": math.ceil(first_half * RUNNING_CADENCE_MULTIPLIER),
                "second_half": math.ceil(second_half * RUNNING_CADENCE_MULTIPLIER),
                "direction": (
                    "up"
                    if second_half - first_half > 0.5
                    else "down" if second_half - first_half < -0.5 else "flat"
                ),
            }

        split_paces = []
        split_heart_rates = []
        max_full_km = int(cumulative // 1000)
        prev_dt = valid_points[0]["time"]
        prev_index = 0

        for km in range(1, max_full_km + 1):
            target = km * 1000
            mark_dt = None
            end_index = None
            for i in range(prev_index + 1, len(valid_points)):
                if valid_points[i]["cum"] >= target:
                    prev = valid_points[i - 1]
                    curr = valid_points[i]
                    seg_dist = curr["cum"] - prev["cum"]
                    frac = 0.0 if seg_dist == 0 else (target - prev["cum"]) / seg_dist
                    mark_dt = prev["time"] + (curr["time"] - prev["time"]) * frac
                    end_index = i
                    break
            if mark_dt is None:
                break

            seconds = (mark_dt - prev_dt).total_seconds()
            if seconds > 0:
                pace_seconds = seconds
                split_paces.append(
                    {
                        "km": km,
                        "pace_seconds": int(round(pace_seconds)),
                    }
                )

            hr_values = [
                p["hr"]
                for p in valid_points[prev_index:end_index]
                if p.get("hr") is not None
            ]
            split_heart_rates.append(
                {
                    "km": km,
                    "avg_hr": (
                        math.ceil(sum(hr_values) / len(hr_values))
                        if hr_values
                        else None
                    ),
                }
            )

            prev_dt = mark_dt
            prev_index = max(0, end_index - 1)

        return cadence_trend, split_paces, split_heart_rates

    def to_namedtuple(self, run_from="gpx"):
        d = {
            "id": self.run_id,
            "name": (self.track_name if self.track_name else ""),  # maybe change later
            "type": self.type,
            "subtype": (self.subtype if self.subtype else ""),
            "start_date": self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "end": self.end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "start_date_local": self.start_time_local.strftime("%Y-%m-%d %H:%M:%S"),
            "end_local": self.end_time_local.strftime("%Y-%m-%d %H:%M:%S"),
            "length": self.length,
            "average_heartrate": (
                int(math.ceil(self.average_heartrate))
                if self.average_heartrate
                else None
            ),
            "max_heartrate": (
                int(math.ceil(self.max_heartrate)) if self.max_heartrate else None
            ),
            "average_cadence": self.average_cadence,
            "cadence_trend": (
                json.dumps(self.cadence_trend, ensure_ascii=False)
                if self.cadence_trend
                else None
            ),
            "split_paces": (
                json.dumps(self.split_paces, ensure_ascii=False)
                if self.split_paces
                else None
            ),
            "split_heart_rates": (
                json.dumps(self.split_heart_rates, ensure_ascii=False)
                if self.split_heart_rates
                else None
            ),
            "elevation_gain": (int(self.elevation_gain) if self.elevation_gain else 0),
            "map": run_map(self.polyline_str),
            "start_latlng": self.start_latlng,
        }
        d.update(self.moving_dict)
        # return a nametuple that can use . to get attr
        return namedtuple("x", d.keys())(*d.values())
