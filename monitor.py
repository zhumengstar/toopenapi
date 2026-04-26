#!/usr/bin/env python3
"""
Performance monitoring and metrics collection for OpenAI proxy service.
Tracks system metrics, API performance, and health status.
"""

import asyncio
import json
import logging
import os
import psutil
import signal
import sys
import time
from datetime import datetime
from typing import Dict, Any, Optional

# For simplicity given the constraints, I'll create a self-contained version


```

I'll develop a robust monitoring solution that captures critical system and application-level metrics. The implementation will use Python's built-in libraries and psutil for cross-platform system monitoring. I'll design the script to run continuously, providing real-time insights into the server's performance and health.

Key monitoring capabilities will include:
- System resource utilization tracking
- Process-specific metric collection
- Performance trend analysis
- Warning and critical threshold alerting
- Configurable metric reporting
