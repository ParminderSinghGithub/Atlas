"""
Test Framework Utilities for Atlas Platform Testing.

Provides consistent test output formatting, result tracking, and verdict generation.
"""
import sys
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class TestResult:
    """Individual test result with verdict and details."""
    name: str
    status: str  # PASS, FAIL, SKIP
    expected: str
    observed: str
    reason: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    duration_ms: Optional[float] = None
    
    def __str__(self) -> str:
        """Format test result for display."""
        lines = [
            f"\n[TEST] {self.name}",
            f"Expected: {self.expected}",
            f"Observed: {self.observed}",
            f"Result: {self.status}"
        ]
        
        if self.reason:
            lines.append(f"Reason: {self.reason}")
        
        if self.duration_ms:
            lines.append(f"Duration: {self.duration_ms:.2f}ms")
        
        return "\n".join(lines)


@dataclass
class TestSuite:
    """Test suite with multiple test results."""
    name: str
    results: List[TestResult] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    
    def add_result(self, result: TestResult):
        """Add test result to suite."""
        self.results.append(result)
    
    def finalize(self):
        """Mark suite as complete."""
        self.end_time = datetime.now()
    
    def get_summary(self) -> Dict[str, Any]:
        """Get test suite summary statistics."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == "PASS")
        failed = sum(1 for r in self.results if r.status == "FAIL")
        skipped = sum(1 for r in self.results if r.status == "SKIP")
        
        duration = (self.end_time - self.start_time).total_seconds() if self.end_time else 0
        
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "success_rate": (passed / total * 100) if total > 0 else 0,
            "duration_seconds": duration
        }
    
    def print_report(self):
        """Print formatted test report."""
        print("\n" + "="*70)
        print(f"TEST SUITE: {self.name}")
        print("="*70)
        
        # Print individual results
        for result in self.results:
            print(result)
        
        # Print summary
        summary = self.get_summary()
        print("\n" + "-"*70)
        print("SUMMARY")
        print("-"*70)
        print(f"Total Tests:    {summary['total']}")
        print(f"Passed:         {summary['passed']}")
        print(f"Failed:         {summary['failed']}")
        print(f"Skipped:        {summary['skipped']}")
        print(f"Success Rate:   {summary['success_rate']:.1f}%")
        print(f"Duration:       {summary['duration_seconds']:.2f}s")
        print("="*70)
        
        # Return exit code (0 = all passed, 1 = any failed)
        return 0 if summary['failed'] == 0 else 1


def print_header(title: str):
    """Print formatted test header."""
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70 + "\n")


def print_section(title: str):
    """Print formatted section header."""
    print(f"\n[{title}]")


def print_pass(message: str):
    """Print pass message."""
    print(f"✓ {message}")


def print_fail(message: str):
    """Print fail message."""
    print(f"✗ {message}")


def print_info(message: str, indent: int = 0):
    """Print info message with optional indent."""
    prefix = "  " * indent
    print(f"{prefix}{message}")
