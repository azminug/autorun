"""
Roblox Multi-Instance RAM Optimizer
====================================
Optimizes RAM usage for multiple Roblox instances.
Best practices implementation for 24/7 operation.
"""

import os
import time
import ctypes
import threading
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass
from datetime import datetime

try:
    import psutil
except ImportError:
    psutil = None

from utils.logger import get_logger


# Windows API for memory management
if os.name == 'nt':
    try:
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        
        # SetProcessWorkingSetSize
        SetProcessWorkingSetSize = kernel32.SetProcessWorkingSetSize
        SetProcessWorkingSetSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t]
        SetProcessWorkingSetSize.restype = ctypes.c_bool
        
        # EmptyWorkingSet
        EmptyWorkingSet = psapi.EmptyWorkingSet
        EmptyWorkingSet.argtypes = [ctypes.c_void_p]
        EmptyWorkingSet.restype = ctypes.c_bool
        
        WINDOWS_API_AVAILABLE = True
    except Exception:
        WINDOWS_API_AVAILABLE = False
else:
    WINDOWS_API_AVAILABLE = False


@dataclass
class RamOptimizerConfig:
    """Configuration for RAM optimizer"""
    max_instances: int = 15
    check_interval_seconds: int = 300  # 5 minutes
    ram_threshold_percent: float = 85.0  # Start optimization when > 85%
    working_set_limit_mb: int = 512  # Max RAM per instance in MB
    min_working_set_mb: int = 128  # Min RAM per instance in MB
    aggressive_threshold_percent: float = 92.0  # Aggressive mode when > 92%
    safe_mode: bool = True  # Conservative optimization
    process_priority: str = "below_normal"  # below_normal, normal, idle


@dataclass
class ProcessInfo:
    """Information about a Roblox process"""
    pid: int
    name: str
    ram_mb: float
    cpu_percent: float
    priority: str
    handle: Optional[int] = None


@dataclass
class OptimizationResult:
    """Result of optimization operation"""
    pid: int
    before_mb: float
    after_mb: float
    saved_mb: float
    success: bool
    error: Optional[str] = None


class RamOptimizer:
    """
    RAM Optimizer for Roblox Multi-Instance
    
    Features:
    - Monitors system RAM usage
    - Optimizes Roblox process working sets
    - Sets process priorities
    - Safe and aggressive modes
    - Background monitoring thread
    """
    
    ROBLOX_PROCESS_NAMES = [
        "RobloxPlayerBeta.exe",
        "RobloxPlayerBeta",
        "RobloxPlayer.exe", 
        "RobloxPlayer",
        "Bloxstrap.exe",
        "Bloxstrap"
    ]
    
    PRIORITY_MAP = {
        "idle": psutil.IDLE_PRIORITY_CLASS if psutil else 64,
        "below_normal": psutil.BELOW_NORMAL_PRIORITY_CLASS if psutil else 16384,
        "normal": psutil.NORMAL_PRIORITY_CLASS if psutil else 32,
        "above_normal": psutil.ABOVE_NORMAL_PRIORITY_CLASS if psutil else 32768,
    }
    
    def __init__(self, config: Optional[RamOptimizerConfig] = None, logger=None):
        self.config = config or RamOptimizerConfig()
        self.logger = logger or get_logger()
        
        # Check dependencies
        if psutil is None:
            self.logger.warning("⚠️ psutil not installed. RAM optimizer disabled.")
            self.enabled = False
            return
        
        self.enabled = True
        
        # Statistics
        self.stats = {
            "cycles": 0,
            "total_saved_mb": 0.0,
            "optimizations": 0,
            "last_optimization": None,
            "errors": 0
        }
        
        # Background thread
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._on_optimization_callback: Optional[Callable] = None
        
        self.logger.info(f"🧠 RAM Optimizer initialized (Threshold: {self.config.ram_threshold_percent}%)")
    
    def get_system_memory(self) -> Dict:
        """Get system memory usage information"""
        if not self.enabled:
            return {}
        
        try:
            mem = psutil.virtual_memory()
            return {
                "total_gb": round(mem.total / (1024**3), 2),
                "used_gb": round(mem.used / (1024**3), 2),
                "free_gb": round(mem.available / (1024**3), 2),
                "usage_percent": mem.percent
            }
        except Exception as e:
            self.logger.error(f"Error getting memory info: {e}")
            return {}
    
    def get_roblox_processes(self) -> List[ProcessInfo]:
        """Get all running Roblox processes"""
        if not self.enabled:
            return []
        
        processes = []
        
        try:
            for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
                try:
                    pinfo = proc.info
                    name = pinfo.get('name', '')
                    
                    # Check if it's a Roblox process
                    if any(roblox_name.lower() in name.lower() 
                           for roblox_name in self.ROBLOX_PROCESS_NAMES):
                        
                        mem_info = pinfo.get('memory_info')
                        ram_mb = mem_info.rss / (1024**2) if mem_info else 0
                        
                        try:
                            priority = proc.nice()
                            priority_name = self._get_priority_name(priority)
                        except:
                            priority_name = "unknown"
                        
                        processes.append(ProcessInfo(
                            pid=pinfo['pid'],
                            name=name,
                            ram_mb=round(ram_mb, 2),
                            cpu_percent=round(pinfo.get('cpu_percent', 0), 2),
                            priority=priority_name,
                            handle=None
                        ))
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                    
        except Exception as e:
            self.logger.error(f"Error getting Roblox processes: {e}")
        
        return processes
    
    def _get_priority_name(self, priority_value: int) -> str:
        """Convert priority value to name"""
        for name, value in self.PRIORITY_MAP.items():
            if value == priority_value:
                return name
        return "unknown"
    
    def optimize_process(self, pid: int) -> OptimizationResult:
        """Optimize a single process's working set"""
        if not self.enabled:
            return OptimizationResult(pid=pid, before_mb=0, after_mb=0, saved_mb=0, 
                                      success=False, error="Optimizer disabled")
        
        try:
            proc = psutil.Process(pid)
            
            # Get before memory
            before_mb = proc.memory_info().rss / (1024**2)
            
            if WINDOWS_API_AVAILABLE:
                # Use Windows API to trim working set
                handle = proc.handle if hasattr(proc, 'handle') else None
                
                if handle is None:
                    # Get process handle
                    PROCESS_SET_QUOTA = 0x0100
                    PROCESS_QUERY_INFORMATION = 0x0400
                    handle = kernel32.OpenProcess(
                        PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, 
                        False, 
                        pid
                    )
                
                if handle:
                    # SetProcessWorkingSetSize with -1, -1 triggers a trim
                    success = SetProcessWorkingSetSize(handle, -1, -1)
                    
                    if not success and not self.config.safe_mode:
                        # Try EmptyWorkingSet (more aggressive)
                        EmptyWorkingSet(handle)
                    
                    # Close handle if we opened it
                    if not hasattr(proc, 'handle'):
                        kernel32.CloseHandle(handle)
            else:
                # Unix/fallback: no direct equivalent, but can trigger GC
                pass
            
            # Small delay for memory to settle
            time.sleep(0.1)
            
            # Get after memory
            after_mb = proc.memory_info().rss / (1024**2)
            saved_mb = before_mb - after_mb
            
            return OptimizationResult(
                pid=pid,
                before_mb=round(before_mb, 2),
                after_mb=round(after_mb, 2),
                saved_mb=round(saved_mb, 2),
                success=True
            )
            
        except psutil.NoSuchProcess:
            return OptimizationResult(pid=pid, before_mb=0, after_mb=0, saved_mb=0,
                                      success=False, error="Process not found")
        except psutil.AccessDenied:
            return OptimizationResult(pid=pid, before_mb=0, after_mb=0, saved_mb=0,
                                      success=False, error="Access denied (run as admin)")
        except Exception as e:
            return OptimizationResult(pid=pid, before_mb=0, after_mb=0, saved_mb=0,
                                      success=False, error=str(e))
    
    def set_process_priority(self, pid: int, priority: str = None) -> bool:
        """Set process priority"""
        if not self.enabled:
            return False
        
        priority = priority or self.config.process_priority
        priority_value = self.PRIORITY_MAP.get(priority, self.PRIORITY_MAP["below_normal"])
        
        try:
            proc = psutil.Process(pid)
            proc.nice(priority_value)
            return True
        except Exception as e:
            self.logger.debug(f"Could not set priority for PID {pid}: {e}")
            return False
    
    def optimize_all(self, force: bool = False) -> Dict:
        """
        Optimize all Roblox processes if needed.
        
        Returns:
            Dict with optimization results
        """
        if not self.enabled:
            return {"enabled": False}
        
        self.stats["cycles"] += 1
        
        # Get system memory
        mem_info = self.get_system_memory()
        if not mem_info:
            return {"error": "Could not get memory info"}
        
        # Get Roblox processes
        processes = self.get_roblox_processes()
        
        result = {
            "timestamp": datetime.now().isoformat(),
            "cycle": self.stats["cycles"],
            "system_ram": mem_info,
            "instance_count": len(processes),
            "optimized": False,
            "results": []
        }
        
        if not processes:
            result["message"] = "No Roblox instances running"
            return result
        
        # Calculate total Roblox RAM
        total_roblox_mb = sum(p.ram_mb for p in processes)
        avg_per_instance = total_roblox_mb / len(processes) if processes else 0
        
        result["total_roblox_mb"] = round(total_roblox_mb, 2)
        result["avg_per_instance_mb"] = round(avg_per_instance, 2)
        
        # Determine if optimization is needed
        needs_optimization = force or (
            mem_info.get("usage_percent", 0) > self.config.ram_threshold_percent
        )
        
        aggressive_mode = (
            mem_info.get("usage_percent", 0) > self.config.aggressive_threshold_percent
        )
        
        if needs_optimization:
            self.logger.info(
                f"🔧 RAM optimization triggered "
                f"({'aggressive' if aggressive_mode else 'safe'} mode, "
                f"RAM: {mem_info.get('usage_percent', 0):.1f}%)"
            )
            
            total_saved = 0.0
            
            # Sort by RAM usage (highest first)
            processes.sort(key=lambda p: p.ram_mb, reverse=True)
            
            for proc in processes:
                # Set priority first
                self.set_process_priority(proc.pid)
                
                # Optimize if above minimum threshold
                if proc.ram_mb > self.config.min_working_set_mb:
                    opt_result = self.optimize_process(proc.pid)
                    result["results"].append(opt_result.__dict__)
                    
                    if opt_result.success:
                        total_saved += opt_result.saved_mb
                        self.logger.debug(
                            f"  PID {proc.pid}: {opt_result.before_mb:.1f} MB → "
                            f"{opt_result.after_mb:.1f} MB (saved {opt_result.saved_mb:.1f} MB)"
                        )
                    else:
                        self.stats["errors"] += 1
            
            result["optimized"] = True
            result["total_saved_mb"] = round(total_saved, 2)
            
            # Update stats
            self.stats["total_saved_mb"] += total_saved
            self.stats["optimizations"] += 1
            self.stats["last_optimization"] = datetime.now().isoformat()
            
            if total_saved > 0:
                self.logger.info(f"✅ RAM optimized: saved {total_saved:.1f} MB")
            
            # Callback
            if self._on_optimization_callback:
                try:
                    self._on_optimization_callback(result)
                except:
                    pass
        else:
            result["message"] = f"RAM usage normal ({mem_info.get('usage_percent', 0):.1f}%)"
            
            # Still set priorities
            for proc in processes:
                self.set_process_priority(proc.pid)
        
        return result
    
    def get_status(self) -> Dict:
        """Get current status and statistics"""
        mem_info = self.get_system_memory()
        processes = self.get_roblox_processes()
        
        return {
            "enabled": self.enabled,
            "system_memory": mem_info,
            "roblox_instances": len(processes),
            "total_roblox_ram_mb": round(sum(p.ram_mb for p in processes), 2),
            "config": {
                "threshold_percent": self.config.ram_threshold_percent,
                "check_interval": self.config.check_interval_seconds,
                "max_instances": self.config.max_instances
            },
            "stats": self.stats,
            "monitoring": self._monitor_thread is not None and self._monitor_thread.is_alive()
        }
    
    def start_monitoring(self, callback: Optional[Callable] = None):
        """Start background monitoring thread"""
        if not self.enabled:
            self.logger.warning("Cannot start monitoring - optimizer disabled")
            return
        
        if self._monitor_thread and self._monitor_thread.is_alive():
            self.logger.warning("Monitoring already running")
            return
        
        self._on_optimization_callback = callback
        self._stop_event.clear()
        
        def monitor_loop():
            self.logger.info(
                f"🧠 RAM monitor started (interval: {self.config.check_interval_seconds}s, "
                f"threshold: {self.config.ram_threshold_percent}%)"
            )
            
            while not self._stop_event.is_set():
                try:
                    result = self.optimize_all()
                    
                    # Log summary
                    if result.get("instance_count", 0) > 0:
                        mem = result.get("system_ram", {})
                        self.logger.debug(
                            f"📊 RAM: {mem.get('usage_percent', 0):.1f}% | "
                            f"Roblox: {result.get('total_roblox_mb', 0):.0f} MB / "
                            f"{result.get('instance_count', 0)} instances"
                        )
                    
                except Exception as e:
                    self.logger.error(f"Error in RAM monitor: {e}")
                    self.stats["errors"] += 1
                
                # Wait for next check or stop signal
                self._stop_event.wait(self.config.check_interval_seconds)
            
            self.logger.info("🧠 RAM monitor stopped")
        
        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()
    
    def stop_monitoring(self):
        """Stop background monitoring thread"""
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._stop_event.set()
            self._monitor_thread.join(timeout=5)
            self.logger.info("RAM monitoring stopped")
    
    def print_status(self):
        """Print formatted status to console"""
        status = self.get_status()
        
        print("\n╔════════════════════════════════════════════╗")
        print("║        RAM Optimizer Status                ║")
        print("╚════════════════════════════════════════════╝")
        
        mem = status.get("system_memory", {})
        print(f"\n📊 System RAM: {mem.get('used_gb', 0):.1f} / {mem.get('total_gb', 0):.1f} GB "
              f"({mem.get('usage_percent', 0):.1f}%)")
        
        print(f"🎮 Roblox Instances: {status.get('roblox_instances', 0)}")
        print(f"💾 Total Roblox RAM: {status.get('total_roblox_ram_mb', 0):.1f} MB")
        
        stats = status.get("stats", {})
        print(f"\n📈 Statistics:")
        print(f"   Cycles: {stats.get('cycles', 0)}")
        print(f"   Optimizations: {stats.get('optimizations', 0)}")
        print(f"   Total Saved: {stats.get('total_saved_mb', 0):.1f} MB")
        print(f"   Errors: {stats.get('errors', 0)}")
        
        print(f"\n⚙️ Config:")
        cfg = status.get("config", {})
        print(f"   Threshold: {cfg.get('threshold_percent', 85)}%")
        print(f"   Interval: {cfg.get('check_interval', 300)}s")
        print(f"   Monitoring: {'Running' if status.get('monitoring') else 'Stopped'}")
        print()


# Singleton instance
_ram_optimizer: Optional[RamOptimizer] = None


def get_ram_optimizer(config: Optional[RamOptimizerConfig] = None) -> RamOptimizer:
    """Get or create RAM optimizer singleton"""
    global _ram_optimizer
    
    if _ram_optimizer is None:
        _ram_optimizer = RamOptimizer(config)
    
    return _ram_optimizer


def optimize_ram_now() -> Dict:
    """Quick function to optimize RAM immediately"""
    optimizer = get_ram_optimizer()
    return optimizer.optimize_all(force=True)
