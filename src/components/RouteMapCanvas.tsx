import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import * as polyline from '@mapbox/polyline';
import type { Activity } from '../types';
import { useLocale } from '../hooks/useLocale';
import './RouteMap.css';

export interface RouteMapProps {
  activities: Activity[];
  selectedActivity?: Activity | null;
  dark?: boolean;
  onClearSelection?: () => void;
}

const routeCache = new WeakMap<
  Activity,
  {
    type: 'Feature';
    properties: { type: string };
    geometry: { type: 'LineString'; coordinates: number[][] };
  }[]
>();

const PI = Math.PI;
const AXIS = 6378245;
const OFFSET = 0.006693421622965943;

function outsideChina(lng: number, lat: number) {
  return lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271;
}

function transformLat(lng: number, lat: number) {
  let value =
    -100 +
    2 * lng +
    3 * lat +
    0.2 * lat * lat +
    0.1 * lng * lat +
    0.2 * Math.sqrt(Math.abs(lng));
  value +=
    ((20 * Math.sin(6 * lng * PI) + 20 * Math.sin(2 * lng * PI)) * 2) / 3;
  value += ((20 * Math.sin(lat * PI) + 40 * Math.sin((lat / 3) * PI)) * 2) / 3;
  return (
    value +
    ((160 * Math.sin((lat / 12) * PI) + 320 * Math.sin((lat * PI) / 30)) * 2) /
      3
  );
}

function transformLng(lng: number, lat: number) {
  let value =
    300 +
    lng +
    2 * lat +
    0.1 * lng * lng +
    0.1 * lng * lat +
    0.1 * Math.sqrt(Math.abs(lng));
  value +=
    ((20 * Math.sin(6 * lng * PI) + 20 * Math.sin(2 * lng * PI)) * 2) / 3;
  value += ((20 * Math.sin(lng * PI) + 40 * Math.sin((lng / 3) * PI)) * 2) / 3;
  return (
    value +
    ((150 * Math.sin((lng / 12) * PI) + 300 * Math.sin((lng / 30) * PI)) * 2) /
      3
  );
}

function wgs84ToGcj02([lng, lat]: number[]) {
  if (outsideChina(lng, lat)) return [lng, lat];
  let dLat = transformLat(lng - 105, lat - 35);
  let dLng = transformLng(lng - 105, lat - 35);
  const radLat = (lat / 180) * PI;
  let magic = Math.sin(radLat);
  magic = 1 - OFFSET * magic * magic;
  const sqrtMagic = Math.sqrt(magic);
  dLat = (dLat * 180) / (((AXIS * (1 - OFFSET)) / (magic * sqrtMagic)) * PI);
  dLng = (dLng * 180) / ((AXIS / sqrtMagic) * Math.cos(radLat) * PI);
  return [lng + dLng, lat + dLat];
}

export function RouteMapCanvas({
  activities,
  selectedActivity,
  dark,
  onClearSelection,
}: RouteMapProps) {
  const { locale } = useLocale();
  const zh = locale === 'zh';
  const panelRef = useRef<HTMLElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const styleReadyRef = useRef(false);
  const cameraRef = useRef<maplibregl.CameraOptions | null>(null);
  const fittedRef = useRef<unknown>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>(
    'loading'
  );
  const [retry, setRetry] = useState(0);
  const style = useMemo<maplibregl.StyleSpecification>(
    () => ({
      version: 8,
      sources: {
        amap: {
          type: 'raster',
          tiles: [
            'https://webst01.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}',
          ],
          tileSize: 256,
          attribution: '© 高德地图',
        },
      },
      layers: [
        {
          id: 'background',
          type: 'background',
          paint: { 'background-color': dark ? '#111827' : '#f1f5f9' },
        },
        { id: 'amap', type: 'raster', source: 'amap' },
      ],
    }),
    [dark]
  );

  const routes = useMemo(() => {
    const items = selectedActivity ? [selectedActivity] : activities;
    return items.flatMap((activity) => {
      const cached = routeCache.get(activity);
      if (cached) return cached;
      if (!activity.summary_polyline) return [];
      try {
        let coordinates = polyline
          .decode(activity.summary_polyline)
          .map(([lat, lng]) => [lng, lat])
          .filter(
            ([lng, lat]) =>
              Number.isFinite(lng) &&
              Number.isFinite(lat) &&
              Math.abs(lng) <= 180 &&
              Math.abs(lat) <= 90
          );
        coordinates = coordinates.map(wgs84ToGcj02);
        if (coordinates.length < 2) return [];
        const features = [
          {
            type: 'Feature' as const,
            properties: { type: activity.type },
            geometry: { type: 'LineString' as const, coordinates },
          },
        ];
        routeCache.set(activity, features);
        return features;
      } catch {
        return [];
      }
    });
  }, [activities, selectedActivity]);

  const routeBounds = useMemo(() => {
    const bounds = new maplibregl.LngLatBounds();
    for (const route of routes) {
      for (const coord of route.geometry.coordinates)
        bounds.extend(coord as [number, number]);
    }
    return bounds;
  }, [routes]);

  const focusedBounds = useMemo(() => {
    return routeBounds;
  }, [routes, routeBounds, selectedActivity]);

  const fitRoutes = useCallback(() => {
    const map = mapRef.current;
    if (!map || focusedBounds.isEmpty()) return;
    map.fitBounds(focusedBounds, {
      padding: { top: 35, bottom: 35, left: 35, right: 65 },
      maxZoom: selectedActivity ? 16 : 13,
      duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches
        ? 0
        : 500,
    });
  }, [focusedBounds, selectedActivity]);

  const drawRoutes = useCallback(() => {
    const map = mapRef.current;
    if (!map || !styleReadyRef.current) return;
    const data = { type: 'FeatureCollection' as const, features: routes };
    const source = map.getSource('routes') as
      maplibregl.GeoJSONSource | undefined;
    if (source) source.setData(data);
    else {
      map.addSource('routes', { type: 'geojson', data });
      map.addLayer({
        id: 'route-casing',
        type: 'line',
        source: 'routes',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': dark ? '#111827' : '#ffffff',
          'line-width': selectedActivity ? 6 : 4,
          'line-opacity': selectedActivity ? 0.9 : 0.65,
        },
      });
      map.addLayer({
        id: 'routes',
        type: 'line',
        source: 'routes',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': [
            'match',
            ['get', 'type'],
            'Run',
            '#e89b68',
            'Ride',
            '#86b7d9',
            '#e89b68',
          ],
        },
      });
    }
    map.setPaintProperty(
      'route-casing',
      'line-width',
      selectedActivity ? 4 : 3
    );
    map.setPaintProperty('routes', 'line-width', selectedActivity ? 2.5 : 1.5);
    map.setPaintProperty('routes', 'line-opacity', selectedActivity ? 1 : 0.82);
    if (fittedRef.current !== routes) {
      fittedRef.current = routes;
      fitRoutes();
    }
  }, [routes, selectedActivity, fitRoutes]);

  useEffect(() => {
    if (!containerRef.current || !panelRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: { version: 8, sources: {}, layers: [] },
      center: [121.4, 31.2],
      zoom: 10,
      ...cameraRef.current,
      locale: zh
        ? {
            'Map.Title': '跑步路线地图',
            'NavigationControl.ZoomIn': '放大',
            'NavigationControl.ZoomOut': '缩小',
            'NavigationControl.ResetBearing': '恢复朝北',
            'FullscreenControl.Enter': '全屏查看',
            'FullscreenControl.Exit': '退出全屏',
            'AttributionControl.ToggleAttribution': '地图来源',
          }
        : {},
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.addControl(
      new maplibregl.FullscreenControl({ container: panelRef.current }),
      'top-right'
    );
    map.addControl(
      new maplibregl.ScaleControl({ unit: 'metric', maxWidth: 90 }),
      'bottom-left'
    );
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(containerRef.current);
    return () => {
      cameraRef.current = {
        center: map.getCenter(),
        zoom: map.getZoom(),
        bearing: map.getBearing(),
        pitch: map.getPitch(),
      };
      observer.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, [zh]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    let failed = false;
    const onError = (event: maplibregl.ErrorEvent) => {
      failed = true;
      setStatus('error');
    };
    const onIdle = () => {
      if (!failed) setStatus('ready');
    };
    const onLoading = () => setStatus('loading');
    const onStyleLoad = () => {
      styleReadyRef.current = true;
    };
    map.on('error', onError);
    map.on('idle', onIdle);
    map.on('style.load', onStyleLoad);
    map.once('styledataloading', onLoading);
    styleReadyRef.current = false;
    map.setStyle(style, {
      diff: false,
      localFontFamily: undefined,
      localIdeographFontFamily: 'sans-serif',
    });
    const timer = window.setTimeout(() => {
      if (!map.isStyleLoaded()) setStatus('error');
    }, 15000);
    return () => {
      window.clearTimeout(timer);
      map.off('error', onError);
      map.off('idle', onIdle);
      map.off('style.load', onStyleLoad);
      map.off('styledataloading', onLoading);
    };
  }, [style, retry, zh]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const onStyleLoad = () => {
      styleReadyRef.current = true;
      drawRoutes();
    };
    map.on('style.load', onStyleLoad);
    drawRoutes();
    return () => {
      map.off('style.load', onStyleLoad);
    };
  }, [drawRoutes, style, retry, zh]);

  useEffect(() => {
    let wasFullscreen = document.fullscreenElement === panelRef.current;
    let frame = 0;
    const onFullscreen = () => {
      const isFullscreen = document.fullscreenElement === panelRef.current;
      if (isFullscreen || wasFullscreen) {
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
          mapRef.current?.resize();
          fitRoutes();
        });
      }
      wasFullscreen = isFullscreen;
    };
    document.addEventListener('fullscreenchange', onFullscreen);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener('fullscreenchange', onFullscreen);
    };
  }, [fitRoutes]);

  return (
    <section
      ref={panelRef}
      className="route-map"
      aria-label={zh ? '路线地图' : 'Route map'}
    >
      <div className="route-map-header">
        <div className="min-w-0">
          <h2 className="text-base font-semibold">
            {zh ? '路线地图' : 'Route map'}
          </h2>
          <p
            className="truncate text-xs text-[var(--color-muted)]"
            title={selectedActivity?.name}
          >
            {selectedActivity
              ? `${selectedActivity.name} · ${(selectedActivity.distance / 1000).toFixed(1)} km`
              : `${routes.length.toLocaleString()} ${zh ? '条轨迹' : 'routes'}`}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          {selectedActivity && onClearSelection && (
            <button className="route-map-action" onClick={onClearSelection}>
              {zh ? '返回总览' : 'Overview'}
            </button>
          )}
          <button
            className="route-map-action"
            disabled={!routes.length}
            onClick={fitRoutes}
            title={zh ? '定位主要轨迹区域' : 'Fit the main route area'}
          >
            {zh ? '定位轨迹' : 'Fit routes'}
          </button>
        </div>
      </div>
      <div className="route-map-body">
        <div
          ref={containerRef}
          className="h-full w-full"
          role="region"
          aria-label={zh ? '跑步路线地图' : 'Running route map'}
        />
        {!routes.length && (
          <div className="route-map-empty" role="status">
            {zh
              ? selectedActivity
                ? '这次活动没有 GPS 轨迹'
                : '当前筛选没有 GPS 轨迹'
              : 'No GPS route available'}
          </div>
        )}
      </div>
      <div className="route-map-footer">
        <span role="status" aria-live="polite">
          {status === 'error'
            ? zh
              ? '底图加载失败，请重试'
              : 'Basemap failed to load'
            : status === 'loading'
              ? zh
                ? '正在加载地图…'
                : 'Loading map…'
              : zh
                ? '底图 · 高德地图'
                : 'Basemap · Amap'}
        </span>
        {status === 'error' && (
          <button
            className="route-map-action"
            onClick={() => {
              setRetry((value) => value + 1);
            }}
          >
            {zh ? '重试' : 'Retry'}
          </button>
        )}
      </div>
    </section>
  );
}
