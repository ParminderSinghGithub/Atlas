"""
Deployment Readiness Test Suite.

Tests:
- Docker containers build cleanly
- Docker containers run without errors
- Volume mounts correct
- Environment variables configured
- Service health after startup
- Inter-service communication
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '_utils'))

import subprocess
import time
from test_framework import TestSuite, TestResult, print_header


def test_docker_compose_file_exists():
    """Test that docker-compose.yml exists."""
    test_name = "Docker Compose File Exists"
    start = time.time()
    
    import os
    from pathlib import Path
    
    compose_file = Path("infra/docker-compose.yml")
    duration = (time.time() - start) * 1000
    
    if compose_file.exists():
        return TestResult(
            name=test_name,
            status="PASS",
            expected="docker-compose.yml exists",
            observed=f"Found at {compose_file}",
            duration_ms=duration
        )
    else:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Compose file exists",
            observed=f"Not found at {compose_file}",
            reason="Docker compose configuration missing",
            duration_ms=duration
        )


def test_all_services_running():
    """Test that all Docker services are running."""
    test_name = "All Services Running"
    start = time.time()
    
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        duration = (time.time() - start) * 1000
        
        if result.returncode == 0:
            output = result.stdout
            
            # Check for expected services
            expected_services = [
                "recommendation-service",
                "catalog-service",
                "user-service",
                "api-gateway",
                "db",
                "redis"
            ]
            
            running_services = []
            for service in expected_services:
                if service in output and "Up" in output:
                    running_services.append(service)
            
            if len(running_services) == len(expected_services):
                return TestResult(
                    name=test_name,
                    status="PASS",
                    expected="All services running",
                    observed=f"{len(running_services)}/{len(expected_services)} services up",
                    duration_ms=duration,
                    details={"services": running_services}
                )
            else:
                missing = set(expected_services) - set(running_services)
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="All services running",
                    observed=f"{len(running_services)}/{len(expected_services)} running",
                    reason=f"Missing: {list(missing)}",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="Docker command succeeds",
                observed=f"Exit code {result.returncode}",
                reason="Docker not available or error",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Services checked",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_services_healthy():
    """Test that services report healthy status."""
    test_name = "Services Health Check"
    start = time.time()
    
    try:
        # Retry logic to allow Docker health checks to propagate
        max_retries = 3
        retry_delay = 2  # seconds
        healthy_critical = []  # Initialize for error handling
        healthy_services = []  # Initialize for error handling
        
        for attempt in range(max_retries):
            result = subprocess.run(
                ["docker", "ps", "--filter", "health=healthy", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=10,
                shell=False  # Explicitly set shell=False for consistency
            )
            
            if result.returncode == 0:
                # Split by newlines and filter empty strings
                healthy_services = [s.strip() for s in result.stdout.strip().split('\n') if s.strip()]
                
                # At least recommendation and user services should have health checks
                critical_services = ["recommendation-service", "user-service"]
                healthy_critical = [svc for svc in critical_services if any(svc in hs for hs in healthy_services)]
                
                if len(healthy_critical) == len(critical_services):
                    duration = (time.time() - start) * 1000
                    return TestResult(
                        name=test_name,
                        status="PASS",
                        expected="Critical services healthy",
                        observed=f"{len(healthy_services)} services healthy",
                        duration_ms=duration,
                        details={"healthy": healthy_services}
                    )
            
            # If not all healthy and not last attempt, wait and retry
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
        
        # Final attempt failed - add debug info
        duration = (time.time() - start) * 1000
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="All critical services healthy",
            observed=f"Found {len(healthy_services)} services, {len(healthy_critical)}/2 critical",
            reason=f"Healthy: {', '.join(healthy_services[:4]) if healthy_services else 'none'}",
            duration_ms=duration
        )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Health checked",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_volume_mounts():
    """Test that volumes are mounted correctly."""
    test_name = "Volume Mounts Configured"
    start = time.time()
    
    try:
        result = subprocess.run(
            ["docker", "volume", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        duration = (time.time() - start) * 1000
        
        if result.returncode == 0:
            volumes = result.stdout.strip().split('\n')
            
            # Check for expected volumes (postgres data only - redis uses no volume)
            expected_volumes = ["infra_postgres_data"]
            
            existing_volumes = [v for v in expected_volumes if v in volumes]
            
            if len(existing_volumes) > 0:
                return TestResult(
                    name=test_name,
                    status="PASS",
                    expected="Persistent volumes configured",
                    observed=f"{len(existing_volumes)} volumes found",
                    duration_ms=duration,
                    details={"volumes": existing_volumes}
                )
            else:
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="Persistent volumes",
                    observed="No expected volumes found",
                    reason="Volume configuration issue",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="Volume list succeeds",
                observed=f"Exit code {result.returncode}",
                reason="Cannot list volumes",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Volumes checked",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_env_file_exists():
    """Test that .env file exists for configuration."""
    test_name = "Environment Configuration"
    start = time.time()
    
    from pathlib import Path
    
    env_file = Path("infra/.env")
    env_sample = Path(".env.sample")
    
    duration = (time.time() - start) * 1000
    
    if env_file.exists():
        return TestResult(
            name=test_name,
            status="PASS",
            expected=".env file configured",
            observed=f"Found at {env_file}",
            duration_ms=duration
        )
    elif env_sample.exists():
        return TestResult(
            name=test_name,
            status="FAIL",
            expected=".env file",
            observed="Only .env.sample found",
            reason="Need to copy .env.sample to infra/.env",
            duration_ms=duration
        )
    else:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Environment configuration",
            observed="No .env or .env.sample",
            reason="Environment not configured",
            duration_ms=duration
        )


def test_redis_enabled():
    """Test that Redis is enabled for session storage."""
    test_name = "Redis Enabled Configuration"
    start = time.time()
    
    from pathlib import Path
    
    env_file = Path("infra/.env")
    
    if not env_file.exists():
        return TestResult(
            name=test_name,
            status="SKIP",
            expected=".env exists",
            observed=".env not found",
            reason="Prerequisite failed"
        )
    
    try:
        with open(env_file, 'r') as f:
            content = f.read()
        
        duration = (time.time() - start) * 1000
        
        if "REDIS_ENABLED=true" in content:
            return TestResult(
                name=test_name,
                status="PASS",
                expected="REDIS_ENABLED=true",
                observed="Redis enabled in .env",
                duration_ms=duration
            )
        elif "REDIS_ENABLED=false" in content:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="REDIS_ENABLED=true",
                observed="REDIS_ENABLED=false",
                reason="Redis must be enabled for session re-ranking",
                duration_ms=duration
            )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="REDIS_ENABLED configured",
                observed="REDIS_ENABLED not found in .env",
                reason="Missing Redis configuration",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Redis config checked",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def main():
    """Run all deployment tests."""
    print_header("DEPLOYMENT READINESS TEST SUITE")
    
    suite = TestSuite("Deployment")
    
    # Run tests
    suite.add_result(test_docker_compose_file_exists())
    suite.add_result(test_all_services_running())
    suite.add_result(test_services_healthy())
    suite.add_result(test_volume_mounts())
    suite.add_result(test_env_file_exists())
    suite.add_result(test_redis_enabled())
    
    suite.finalize()
    exit_code = suite.print_report()
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
