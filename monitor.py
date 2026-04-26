#!/usr/bin/env python3
"""
OpenAI Proxy Service Monitoring Suite
Comprehensive monitoring for system resources, application performance, and API health

Features:
- System metrics (CPU, memory, disk, network)
- Process-specific monitoring (CPU, memory, file descriptors, threads)
- API endpoint health checking with request/response timing
- Prometheus-compatible metrics export
- Alerts and notifications (console, file, external webhook)
- Historical data storage with configurable retention
- Configurable check intervals and thresholds
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import psutil
from aiohttp import web

# ==================== Configuration ====================


@dataclass
class MonitorConfig:
    """Monitoring configuration"""

    # Service configuration
    service_name: str = "openai-proxy"
    service_port: int = int(os.getenv("PORT", "8787"))
    service_pid: Optional[int] = None

    # Monitoring intervals (seconds)
    system_interval: int = 5  # System metrics collection interval
    process_interval: int = 5  # Process metrics collection interval
    health_interval: int = 10  # Health check interval
    api_interval: int = 60  # API endpoint test interval

    # Thresholds (alerts triggered when exceeded)
    cpu_threshold: float = 80.0  # CPU usage percentage
    memory_threshold: float = 85.0  # Memory usage percentage
    disk_threshold: float = 90.0  # Disk usage percentage
    response_time_threshold: float = 5.0  # API response time threshold

    # Data retention
    max_history_points: int = 1000  # Maximum data points to keep in memory
    log_retention_days: int = 7  # Log retention days

    # Output configuration
    log_file: str = "/tmp/openai_proxy_monitor.log"
    metrics_file: str = "/tmp/openai_proxy_metrics.json"
    prometheus_file: str = "/tmp/openai_proxy_prometheus.prom"
    enable_prometheus: bool = True
    alert_webhook: Optional[str] = None  # Optional: webhook URL for alerts

    # API endpoints to monitor
    health_endpoint: str = "http://localhost:%d/health" % service_port
    models_endpoint: str = "http://localhost:%d/v1/models" % service_port
    chat_endpoint: str = "http://localhost:%d/v1/chat/completions" % service_port


# Global configuration
config = MonitorConfig()


# ==================== Metrics Collection ====================


class MetricsCollector:
    """Collects system and application metrics"""

    def __init__(self, config: MonitorConfig):
        self.config = config
        self.history = {
            "timestamps": deque(maxlen=config.max_history_points),
            "system_cpu": deque(maxlen=config.max_history_points),
            "system_memory": deque(maxlen=config.max_history_points),
            "system_disk": deque(maxlen=config.max_history_points),
            "process_cpu": deque(maxlen=config.max_history_points),
            "process_memory": deque(maxlen=config.max_history_points),
            "response_times": deque(maxlen=config.max_history_points),
            "api_health": deque(maxlen=config.max_history_points),
        }
        self.alerts = []

    def get_system_metrics(self) -> Dict[str, Any]:
        """Collect system-level metrics"""
        try:
            # CPU usage (percentage)
            cpu_percent = psutil.cpu_percent(interval=1)

            # Memory usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent

            # Disk usage
            disk = psutil.disk_usage("/")
            disk_percent = (disk.used / disk.total) * 100

            # Network I/O (deltas)
            net_before = psutil.net_io_counters()
            time.sleep(0.5)
            net_after = psutil.net_io_counters()

            network_in = (net_after.bytes_recv - net_before.bytes_recv) * 2  # B/s
            network_out = (net_after.bytes_sent - net_before.bytes_sent) * 2

            # Load average (if available)
            try:
                load_avg = os.getloadavg()
            except:
                load_avg = None

            metrics = {
                "timestamp": datetime.now().isoformat(),
                "cpu_percent": round(cpu_percent, 2),
                "memory_percent": round(memory_percent, 2),
                "disk_percent": round(disk_percent, 2),
                "memory_available_mb": round(memory.available / 1024 / 1024, 2),
                "memory_total_mb": round(memory.total / 1024 / 1024, 2),
                "disk_available_gb": round(disk.free / 1024 / 1024 / 1024, 2),
                "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 2),
                "network_in_bytes_s": network_in,
                "network_out_bytes_s": network_out,
                "load_avg": load_avg,
            }

            # Store in history
            self._store_metric("system_cpu", metrics["cpu_percent"])
            self._store_metric("system_memory", metrics["memory_percent"])
            self._store_metric("system_disk", metrics["disk_percent"])

            return metrics

        except Exception as e:
            logging.error(f"Failed to collect system metrics: {e}")
            return {"error": str(e)}

    def get_process_metrics(self, pid: Optional[int] = None) -> Dict[str, Any]:
        """Collect process-specific metrics"""
        try:
            if not pid:
                pid = self.config.service_pid

            if not pid or not psutil.pid_exists(pid):
                return {"error": "Process not found"}

            process = psutil.Process(pid)
            with process.oneshot():
                # CPU usage
                cpu_percent = process.cpu_percent()

                # Memory usage
                memory_info = process.memory_info()
                memory_percent = process.memory_percent()

                # File descriptors
                try:
                    num_fds = process.num_fds()
                except:
                    num_fds = 0

                # Threads
                num_threads = process.num_threads()

                # I/O stats
                try:
                    io_counters = process.io_counters()
                except:
                    io_counters = None

                metrics = {
                    "timestamp": datetime.now().isoformat(),
                    "pid": pid,
                    "exists": True,
                    "cpu_percent": round(cpu_percent, 2),
                    "memory_percent": round(memory_percent, 2),
                    "memory_rss_mb": round(memory_info.rss / 1024 / 1024, 2),
                    "memory_vms_mb": round(memory_info.vms / 1024 / 1024, 2),
                    "num_threads": num_threads,
                    "num_fds": num_fds,
                    "status": process.status(),
                    "create_time": datetime.fromtimestamp(
                        process.create_time()
                    ).isoformat(),
                    "io_read_count": io_counters.read_count if io_counters else 0,
                    "io_write_count": io_counters.write_count if io_counters else 0,
                }

                # Store in history
                self._store_metric("process_cpu", metrics["cpu_percent"])
                self._store_metric("process_memory", metrics["memory_percent"])

                return metrics

        except psutil.NoSuchProcess:
            return {"error": "Process not found", "pid": pid}
        except Exception as e:
            logging.error(f"Failed to collect process metrics: {e}")
            return {"error": str(e)}

    def _store_metric(self, key: str, value: float):
        """Store a metric in the history buffer"""
        if key in self.history:
            self.history[key].append(value)
            if key == "timestamps":
                self.history[key].append(datetime.now().isoformat())

    def get_trend(self, metric: str, period: int = 300) -> Dict[str, float]:
        """Get trend statistics for a metric over specified period (seconds)"""
        try:
            if metric not in self.history or len(self.history[metric]) == 0:
                return {"avg": 0, "min": 0, "max": 0, "count": 0}

            values = list(self.history[metric])
            timestamps = list(self.history["timestamps"])

            # Filter by time period
            cutoff_time = datetime.now() - timedelta(seconds=period)
            filtered_values = []

            for i, ts in enumerate(timestamps):
                if datetime.fromisoformat(ts) >= cutoff_time:
                    filtered_values.append(values[i])

            if not filtered_values:
                return {"avg": 0, "min": 0, "max": 0, "count": 0}

            return {
                "avg": round(sum(filtered_values) / len(filtered_values), 2),
                "min": round(min(filtered_values), 2),
                "max": round(max(filtered_values), 2),
                "count": len(filtered_values),
                "current": filtered_values[-1],
            }
        except Exception as e:
            return {"error": str(e)}


# ==================== Health Checker ====================


class HealthChecker:
    """Performs health checks on API endpoints"""

    def __init__(self, config: MonitorConfig):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=10)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def check_health_endpoint(self) -> Dict[str, Any]:
        """Check health endpoint"""
        try:
            if not self.session:
                return {"error": "Session not initialized"}

            start_time = time.time()
            async with self.session.get(self.config.health_endpoint) as resp:
                response_time = time.time() - start_time
                data = await resp.json() if resp.status == 200 else {}

                return {
                    "endpoint": "health",
                    "status": "healthy" if resp.status == 200 else "unhealthy",
                    "status_code": resp.status,
                    "response_time_sec": round(response_time, 3),
                    "google_api_reachable": data.get("google_api_reachable", False),
                    "timestamp": datetime.now().isoformat(),
                }
        except Exception as e:
            return {
                "endpoint": "health",
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    async def check_models_endpoint(self) -> Dict[str, Any]:
        """Check models endpoint"""
        try:
            if not self.session:
                return {"error": "Session not initialized"}

            start_time = time.time()
            async with self.session.get(self.config.models_endpoint) as resp:
                response_time = time.time() - start_time
                data = await resp.json() if resp.status == 200 else {}

                return {
                    "endpoint": "models",
                    "status": "healthy" if resp.status == 200 else "unhealthy",
                    "status_code": resp.status,
                    "response_time_sec": round(response_time, 3),
                    "model_count": len(data.get("data", [])),
                    "timestamp": datetime.now().isoformat(),
                }
        except Exception as e:
            return {
                "endpoint": "models",
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    async def check_chat_endpoint(self) -> Dict[str, Any]:
        """Test chat completion endpoint with a simple request"""
        try:
            if not self.session:
                return {"error": "Session not initialized"}

            payload = {
                "model": "gemma-4-31b-it",
                "messages": [{"role": "user", "content": "Test"}],
                "max_tokens": 10,
            }

            start_time = time.time()
            async with self.session.post(
                self.config.chat_endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                response_time = time.time() - start_time

                return {
                    "endpoint": "chat",
                    "status": "healthy" if resp.status in [200, 400] else "unhealthy",
                    "status_code": resp.status,
                    "response_time_sec": round(response_time, 3),
                    "timestamp": datetime.now().isoformat(),
                }
        except Exception as e:
            return {
                "endpoint": "chat",
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    async def run_all_checks(self) -> List[Dict[str, Any]]:
        """Run all health checks"""
        checks = [
            await self.check_health_endpoint(),
            await self.check_models_endpoint(),
            await self.check_chat_endpoint(),
        ]
        return checks


# ==================== Alert Manager ====================


class AlertManager:
    """Manages alerts and notifications"""

    def __init__(self, config: MonitorConfig, metrics_collector: MetricsCollector):
        self.config = config
        self.collector = metrics_collector
        self.active_alerts: List[Dict[str, Any]] = []

    def check_thresholds(self) -> List[Dict[str, Any]]:
        """Check metrics against thresholds and generate alerts"""
        alerts = []
        now = datetime.now().isoformat()

        # Check system CPU
        if len(self.collector.history["system_cpu"]) > 0:
            cpu_current = list(self.collector.history["system_cpu"])[-1]
            if cpu_current > self.config.cpu_threshold:
                alerts.append(
                    {
                        "level": "warning",
                        "metric": "system_cpu",
                        "value": cpu_current,
                        "threshold": self.config.cpu_threshold,
                        "message": f"High CPU usage: {cpu_current}%",
                        "timestamp": now,
                    }
                )

        # Check system memory
        if len(self.collector.history["system_memory"]) > 0:
            memory_current = list(self.collector.history["system_memory"])[-1]
            if memory_current > self.config.memory_threshold:
                alerts.append(
                    {
                        "level": "warning",
                        "metric": "system_memory",
                        "value": memory_current,
                        "threshold": self.config.memory_threshold,
                        "message": f"High memory usage: {memory_current}%",
                        "timestamp": now,
                    }
                )

        # Check process if available
        process_metrics = self.collector.get_process_metrics()
        if "error" not in process_metrics:
            if process_metrics["memory_percent"] > self.config.memory_threshold:
                alerts.append(
                    {
                        "level": "warning",
                        "metric": "process_memory",
                        "value": process_metrics["memory_percent"],
                        "threshold": self.config.memory_threshold,
                        "message": f"High process memory: {process_metrics['memory_percent']}%",
                        "timestamp": now,
                    }
                )

        return alerts

    async def send_webhook_alert(self, alert: Dict[str, Any]):
        """Send alert to webhook if configured"""
        if not self.config.alert_webhook:
            return

        try:
            payload = {
                "service": self.config.service_name,
                "alert": alert,
                "timestamp": datetime.now().isoformat(),
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.config.alert_webhook,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status >= 400:
                        logging.error(f"Webhook alert failed: {resp.status}")
        except Exception as e:
            logging.error(f"Failed to send webhook alert: {e}")


# ==================== Metrics Exporter ====================


class MetricsExporter:
    """Exports metrics in various formats"""

    def __init__(self, config: MonitorConfig, collector: MetricsCollector):
        self.config = config
        self.collector = collector

    def export_json(self) -> Dict[str, Any]:
        """Export metrics as JSON"""
        system_metrics = self.collector.get_system_metrics()
        process_metrics = self.collector.get_process_metrics()

        return {
            "service": self.config.service_name,
            "timestamp": datetime.now().isoformat(),
            "system": system_metrics,
            "process": process_metrics,
            "history_summary": {
                "cpu_avg_5m": self.collector.get_trend("system_cpu", 300)["avg"],
                "memory_avg_5m": self.collector.get_trend("system_memory", 300)["avg"],
            },
        }

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format"""
        lines = []

        # System metrics
        system = self.collector.get_system_metrics()
        if "error" not in system:
            lines.append("# HELP openai_proxy_system_cpu_percent CPU usage percentage")
            lines.append("# TYPE openai_proxy_system_cpu_percent gauge")
            lines.append(
                f'openai_proxy_system_cpu_percent {{service="{self.config.service_name}"}} {system["cpu_percent"]}'
            )

            lines.append(
                "# HELP openai_proxy_system_memory_percent Memory usage percentage"
            )
            lines.append("# TYPE openai_proxy_system_memory_percent gauge")
            lines.append(
                f'openai_proxy_system_memory_percent {{service="{self.config.service_name}"}} {system["memory_percent"]}'
            )

            lines.append(
                "# HELP openai_proxy_system_disk_percent Disk usage percentage"
            )
            lines.append("# TYPE openai_proxy_system_disk_percent gauge")
            lines.append(
                f'openai_proxy_system_disk_percent {{service="{self.config.service_name}"}} {system["disk_percent"]}'
            )

        # Process metrics
        process = self.collector.get_process_metrics()
        if "error" not in process:
            lines.append(
                "# HELP openai_proxy_process_cpu_percent Process CPU usage percentage"
            )
            lines.append("# TYPE openai_proxy_process_cpu_percent gauge")
            lines.append(
                f'openai_proxy_process_cpu_percent {{service="{self.config.service_name}"}} {process["cpu_percent"]}'
            )

            lines.append(
                "# HELP openai_proxy_process_memory_percent Process memory usage percentage"
            )
            lines.append("# TYPE openai_proxy_process_memory_percent gauge")
            lines.append(
                f'openai_proxy_process_memory_percent {{service="{self.config.service_name}"}} {process["memory_percent"]}'
            )

        return "\n".join(lines)

    def save_metrics(self):
        """Save metrics to files"""
        try:
            # Save JSON metrics
            json_metrics = self.export_json()
            with open(self.config.metrics_file, "w") as f:
                json.dump(json_metrics, f, indent=2, default=str)

            # Save Prometheus metrics
            if self.config.enable_prometheus:
                prom_metrics = self.export_prometheus()
                with open(self.config.prometheus_file, "w") as f:
                    f.write(prom_metrics)

            # Log to file
            logging.info(json_metrics)

        except Exception as e:
            logging.error(f"Failed to save metrics: {e}")


# ==================== Web Dashboard ====================


class DashboardServer:
    """Provides web dashboard and metrics endpoint"""

    def __init__(
        self, config: MonitorConfig, collector: MetricsCollector, checker: HealthChecker
    ):
        self.config = config
        self.collector = collector
        self.checker = checker
        self.app = web.Application()
        self.setup_routes()

    def setup_routes(self):
        """Setup web routes"""
        self.app.router.add_get("/", self.handle_dashboard)
        self.app.router.add_get("/metrics", self.handle_metrics)
        self.app.router.add_get("/prometheus", self.handle_prometheus)
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/api/metrics", self.handle_json_metrics)

    async def handle_dashboard(self, request: web.Request) -> web.Response:
        """Serve HTML dashboard"""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>OpenAI Proxy Monitor</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
                .container { max-width: 1200px; margin: 0 auto; }
                .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
                .metric-card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                .metric-title { font-size: 18px; font-weight: bold; margin-bottom: 10px; color: #333; }
                .metric-value { font-size: 36px; font-weight: bold; margin: 10px 0; }
                .metric-unit { font-size: 14px; color: #666; }
                .status-ok { color: #28a745; }
                .status-warning { color: #ffc107; }
                .status-error { color: #dc3545; }
                .alert { background: #fff3cd; border: 1px solid #ffc107; padding: 10px; border-radius: 4px; margin: 10px 0; }
                table { width: 100%; border-collapse: collapse; }
                th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
                th { background: #f8f9fa; font-weight: bold; }
                .update-time { text-align: right; color: #666; font-size: 14px; margin-bottom: 20px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>OpenAI Proxy Monitor</h1>
                <div class="update-time">Last updated: <span id="update-time"></span></div>

                <div class="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-title">System CPU</div>
                        <div class="metric-value" id="system-cpu">-</div>
                        <div class="metric-unit">%</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-title">System Memory</div>
                        <div class="metric-value" id="system-memory">-</div>
                        <div class="metric-unit">%</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-title">Process CPU</div>
                        <div class="metric-value" id="process-cpu">-</div>
                        <div class="metric-unit">%</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-title">Process Memory</div>
                        <div class="metric-value" id="process-memory">-</div>
                        <div class="metric-unit">%</div>
                    </div>
                </div>

                <div id="alerts"></div>

                <h2>Endpoints Status</h2>
                <table id="endpoints">
                    <thead>
                        <tr>
                            <th>Endpoint</th>
                            <th>Status</th>
                            <th>Response Time</th>
                            <th>Info</th>
                        </tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>

            <script>
                // Auto-refresh dashboard every 5 seconds
                setInterval(() => {
                    fetch('/api/metrics')
                        .then(r => r.json())
                        .then(data => updateDashboard(data))
                        .catch(err => console.error("Failed to fetch metrics:", err));
                }, 5000);

                function updateDashboard(data) {
                    document.getElementById('update-time').textContent = new Date().toLocaleString();

                    // Update metrics
                    if(data.system && !data.system.error) {
                        document.getElementById('system-cpu').textContent = data.system.cpu_percent;
                        document.getElementById('system-memory').textContent = data.system.memory_percent;
                    }

                    if(data.process && !data.process.error) {
                        document.getElementById('process-cpu').textContent = data.process.cpu_percent;
                        document.getElementById('process-memory').textContent = data.process.memory_percent;
                    }
                }
            </script>
        </body>
        </html>
        """
        return web.Response(text=html, content_type="text/html")

    async def handle_metrics(self, request: web.Request) -> web.Response:
        """Serve metrics dashboard"""
        return web.Response(
            text="Use /api/metrics for JSON or /prometheus for Prometheus format"
        )

    async def handle_prometheus(self, request: web.Request) -> web.Response:
        """Serve Prometheus metrics"""
        prom_metrics = self.collector.export_prometheus()
        return web.Response(text=prom_metrics, content_type="text/plain")

    async def handle_json_metrics(self, request: web.Request) -> web.Response:
        """Serve JSON metrics"""
        metrics = self.collector.export_json()
        return web.Response(
            text=json.dumps(metrics, default=str), content_type="application/json"
        )

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check for monitor"""
        return web.Response(text="OK", status=200)

    def run(self):
        """Start web server"""
        web.run_app(self.app, host="0.0.0.0", port=8080)


# ==================== Main Monitor ====================


class Monitor:
    """Main monitoring service"""

    def __init__(self, config: MonitorConfig):
        self.config = config
        self.collector = MetricsCollector(config)
        self.checker = HealthChecker(config)
        self.exporter = MetricsExporter(config, self.collector)
        self.alert_manager = AlertManager(config, self.collector)
        self.dashboard = None

        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s",
            handlers=[logging.FileHandler(config.log_file), logging.StreamHandler()],
        )

    async def monitor_loop(self):
        """Main monitoring loop"""
        logging.info(f"Starting Monitor for {self.config.service_name}")

        # Finding service PID if not provided
        if not self.config.service_pid:
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                if "async_server.py" in " ".join(proc.info["cmdline"] or []):
                    self.config.service_pid = proc.info["pid"]
                    logging.info(f"Found service PID: {self.config.service_pid}")
                    break

        while True:
            try:
                # Collect metrics
                system_metrics = self.collector.get_system_metrics()
                process_metrics = self.collector.get_process_metrics()

                # Check health endpoints
                async with self.checker:
                    health_results = await self.checker.run_all_checks()

                # Check thresholds and generate alerts
                alerts = self.alert_manager.check_thresholds()

                # Save metrics
                self.exporter.save_metrics()

                # Log current status
                logging.info("=" * 60)
                logging.info(
                    f"System Metrics: {json.dumps(system_metrics, default=str)}"
                )
                logging.info(
                    f"Process Metrics: {json.dumps(process_metrics, default=str)}"
                )
                logging.info(
                    f"Health Checks: {json.dumps(health_results, default=str)}"
                )
                logging.info(f"Alerts: {len(alerts)} active")

                # Send webhook alerts if configured
                for alert in alerts:
                    await self.alert_manager.send_webhook_alert(alert)

                # Wait for next interval
                await asyncio.sleep(self.config.system_interval)

            except Exception as e:
                logging.error(f"Error in monitor loop: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def run(self):
        """Run the monitor"""
        # Start the monitoring loop
        monitor_task = asyncio.create_task(self.monitor_loop())

        # Start dashboard if requested
        if os.getenv("ENABLE_DASHBOARD", "true").lower() == "true":
            self.dashboard = DashboardServer(self.config, self.collector, self.checker)
            dashboard_task = asyncio.create_task(asyncio.to_thread(self.dashboard.run))

        # Wait for tasks
        await asyncio.gather(monitor_task)


# ==================== Command Line Interface ====================


def print_help():
    """Print help message"""
    help_text = """
OpenAI Proxy Monitor

Usage: python monitor.py [options]

Options:
    --service-pid PID      Process ID of the service to monitor (auto-detected if not provided)
    --interval SECONDS    System metrics collection interval (default: 5)
    --health-interval SECONDS Health check interval (default: 10)
    --log-file PATH       Log file path (default: /tmp/openai_proxy_monitor.log)
    --metrics-file PATH   Metrics JSON file path (default: /tmp/openai_proxy_metrics.json)
    --prometheus-file PATH Prometheus metrics file path (default: /tmp/openai_proxy_prometheus.prom)
    --webhook URL         Webhook URL for alerts
    --port PORT           Service port to monitor (default: 8787)
    --no-dashboard        Disable web dashboard
    --help               Show this help message

Examples:
    # Monitor service with auto-detect PID
    python monitor.py

    # Monitor specific PID with custom interval
    python monitor.py --service-pid 12345 --interval 10

    # Monitor with webhook notifications
    python monitor.py --webhook https://hooks.slack.com/services/YOUR/WEBHOOK

    # Run in background with log rotation
    nohup python monitor.py --log-file /var/log/monitor.log &
    """
    print(help_text)


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="OpenAI Proxy Monitor")
    parser.add_argument("--service-pid", type=int, help="Service PID to monitor")
    parser.add_argument(
        "--interval", type=int, default=5, help="Metrics collection interval"
    )
    parser.add_argument(
        "--health-interval", type=int, default=10, help="Health check interval"
    )
    parser.add_argument(
        "--log-file", default="/tmp/openai_proxy_monitor.log", help="Log file path"
    )
    parser.add_argument(
        "--metrics-file",
        default="/tmp/openai_proxy_metrics.json",
        help="Metrics JSON file",
    )
    parser.add_argument(
        "--prometheus-file",
        default="/tmp/openai_proxy_prometheus.prom",
        help="Prometheus metrics file",
    )
    parser.add_argument("--webhook", help="Webhook URL for alerts")
    parser.add_argument("--port", type=int, default=8787, help="Service port")
    parser.add_argument(
        "--no-dashboard", action="store_true", help="Disable web dashboard"
    )
    parser.add_argument("--help", action="help", help="Show help message")

    args = parser.parse_args()

    # Update config
    config = MonitorConfig()
    config.service_port = args.port
    if args.service_pid:
        config.service_pid = args.service_pid
    config.system_interval = args.interval
    config.health_interval = args.health_interval
    config.log_file = args.log_file
    config.metrics_file = args.metrics_file
    config.prometheus_file = args.prometheus_file
    config.alert_webhook = args.webhook

    if args.no_dashboard:
        os.environ["ENABLE_DASHBOARD"] = "false"

    # Create monitor and run
    monitor = Monitor(config)

    try:
        asyncio.run(monitor.run())
    except KeyboardInterrupt:
        logging.info("Monitor stopped by user")
    except Exception as e:
        logging.error(f"Monitor failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
