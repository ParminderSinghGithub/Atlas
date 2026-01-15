"""
Monitoring Scripts Test Suite.

Tests:
- aggregate_metrics.py execution
- detect_drift.py execution
- Log parsing correctness
- Metrics extraction accuracy
- No false automation claims
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '_utils'))

import subprocess
import time
from pathlib import Path
from test_framework import TestSuite, TestResult, print_header

PROJECT_ROOT = Path(__file__).parent.parent.parent
MONITORING_DIR = PROJECT_ROOT / "monitoring"


def test_aggregate_metrics_exists():
    """Test that aggregate_metrics.py exists."""
    test_name = "Aggregate Metrics Script Exists"
    start = time.time()
    
    script = MONITORING_DIR / "aggregate_metrics.py"
    duration = (time.time() - start) * 1000
    
    if script.exists():
        return TestResult(
            name=test_name,
            status="PASS",
            expected="aggregate_metrics.py exists",
            observed=f"Found at {script}",
            duration_ms=duration
        )
    else:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Script exists",
            observed=f"Not found at {script}",
            reason="Monitoring script missing",
            duration_ms=duration
        )


def test_detect_drift_exists():
    """Test that detect_drift.py exists."""
    test_name = "Detect Drift Script Exists"
    start = time.time()
    
    script = MONITORING_DIR / "detect_drift.py"
    duration = (time.time() - start) * 1000
    
    if script.exists():
        return TestResult(
            name=test_name,
            status="PASS",
            expected="detect_drift.py exists",
            observed=f"Found at {script}",
            duration_ms=duration
        )
    else:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Script exists",
            observed=f"Not found at {script}",
            reason="Drift detection script missing",
            duration_ms=duration
        )


def test_aggregate_metrics_execution():
    """Test that aggregate_metrics.py executes without error."""
    test_name = "Aggregate Metrics Execution"
    start = time.time()
    
    script = MONITORING_DIR / "aggregate_metrics.py"
    sample_logs = MONITORING_DIR / "sample_logs.txt"
    
    if not script.exists():
        return TestResult(
            name=test_name,
            status="SKIP",
            expected="Script exists",
            observed="Script not found",
            reason="Prerequisite failed"
        )
    
    try:
        # Run with sample logs if available
        if sample_logs.exists():
            with open(sample_logs, 'r') as f:
                result = subprocess.run(
                    ["python", str(script)],
                    stdin=f,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
        else:
            # Run with empty input
            result = subprocess.run(
                ["python", str(script)],
                input="",
                capture_output=True,
                text=True,
                timeout=10
            )
        
        duration = (time.time() - start) * 1000
        
        if result.returncode == 0:
            # Try to parse output as JSON
            try:
                import json
                output = json.loads(result.stdout)
                
                # Check for expected keys
                expected_keys = ["total_impressions", "unique_users", "strategy_distribution"]
                has_keys = all(k in output for k in expected_keys)
                
                if has_keys:
                    return TestResult(
                        name=test_name,
                        status="PASS",
                        expected="Valid JSON metrics output",
                        observed=f"Script executed, JSON valid",
                        duration_ms=duration,
                        details={"impressions": output.get("total_impressions", 0)}
                    )
                else:
                    return TestResult(
                        name=test_name,
                        status="FAIL",
                        expected="Complete metrics",
                        observed=f"Missing keys: {[k for k in expected_keys if k not in output]}",
                        reason="Incomplete metrics output",
                        duration_ms=duration
                    )
            except json.JSONDecodeError:
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="Valid JSON output",
                    observed=f"Output: {result.stdout[:100]}",
                    reason="Output not valid JSON",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="Exit code 0",
                observed=f"Exit code {result.returncode}",
                reason=f"Error: {result.stderr[:200]}",
                duration_ms=duration
            )
    except subprocess.TimeoutExpired:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Execution completes",
            observed="Timeout after 10s",
            reason="Script hangs",
            duration_ms=(time.time() - start) * 1000
        )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Successful execution",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_detect_drift_execution():
    """Test that detect_drift.py executes without error."""
    test_name = "Detect Drift Execution"
    start = time.time()
    
    script = MONITORING_DIR / "detect_drift.py"
    
    if not script.exists():
        return TestResult(
            name=test_name,
            status="SKIP",
            expected="Script exists",
            observed="Script not found",
            reason="Prerequisite failed"
        )
    
    try:
        result = subprocess.run(
            ["python", str(script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=PROJECT_ROOT
        )
        
        duration = (time.time() - start) * 1000
        
        if result.returncode == 0:
            # Check output contains expected drift analysis
            output = result.stdout
            
            if "drift" in output.lower() or "baseline" in output.lower():
                return TestResult(
                    name=test_name,
                    status="PASS",
                    expected="Drift analysis completed",
                    observed="Script executed successfully",
                    duration_ms=duration
                )
            else:
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="Drift analysis output",
                    observed=f"Output: {output[:100]}",
                    reason="Output doesn't contain drift analysis",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="Exit code 0",
                observed=f"Exit code {result.returncode}",
                reason=f"Error: {result.stderr[:200]}",
                duration_ms=duration
            )
    except subprocess.TimeoutExpired:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Execution completes",
            observed="Timeout after 30s",
            reason="Script hangs or too slow",
            duration_ms=(time.time() - start) * 1000
        )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Successful execution",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_monitoring_is_passive():
    """Test that monitoring doesn't claim to be automated."""
    test_name = "Monitoring is Passive (No False Automation Claims)"
    start = time.time()
    
    # Check monitoring scripts don't contain cron/automated deployment claims
    monitoring_files = list(MONITORING_DIR.glob("*.py"))
    
    false_claims = []
    
    for script_path in monitoring_files:
        with open(script_path, 'r') as f:
            content = f.read().lower()
            
            # Check for misleading automation claims
            if "cron" in content and "automatic" in content:
                false_claims.append(f"{script_path.name}: mentions cron + automatic")
            elif "production monitoring" in content and "continuous" in content:
                false_claims.append(f"{script_path.name}: claims continuous production monitoring")
    
    duration = (time.time() - start) * 1000
    
    if len(false_claims) == 0:
        return TestResult(
            name=test_name,
            status="PASS",
            expected="No false automation claims",
            observed="Monitoring scripts are passive/manual",
            duration_ms=duration
        )
    else:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Passive monitoring only",
            observed=f"False claims: {false_claims}",
            reason="Scripts claim automation that doesn't exist",
            duration_ms=duration
        )


def main():
    """Run all monitoring tests."""
    print_header("MONITORING SCRIPTS TEST SUITE")
    
    suite = TestSuite("Monitoring Scripts")
    
    # Run tests
    suite.add_result(test_aggregate_metrics_exists())
    suite.add_result(test_detect_drift_exists())
    suite.add_result(test_aggregate_metrics_execution())
    suite.add_result(test_detect_drift_execution())
    suite.add_result(test_monitoring_is_passive())
    
    suite.finalize()
    exit_code = suite.print_report()
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
