"""
Master Orchestration Script for Amazon Catalog Integration

This script orchestrates the complete pipeline:
1. Ingest Amazon metadata
2. Normalize categories
3. Seed catalog database
4. Update latent item mappings
5. Verify integration

Usage:
    python tools/run_amazon_integration.py
"""
import asyncio
import subprocess
import sys
from pathlib import Path
import time


class PipelineOrchestrator:
    """Orchestrate Amazon catalog integration pipeline."""
    
    def __init__(self, project_root: Path):
        """Initialize orchestrator."""
        self.project_root = project_root
        self.tools_dir = project_root / "tools"
        self.step_results = []
    
    def run_step(self, step_name: str, script_path: Path, description: str) -> bool:
        """
        Run a pipeline step.
        
        Args:
            step_name: Step identifier
            script_path: Path to Python script
            description: Human-readable description
        
        Returns:
            True if successful, False otherwise
        """
        print("\n" + "="*70)
        print(f"STEP: {step_name}")
        print(f"Description: {description}")
        print("="*70)
        
        start_time = time.time()
        
        try:
            result = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(self.project_root),
                check=True,
                capture_output=False,  # Show output in real-time
                text=True
            )
            
            elapsed = time.time() - start_time
            self.step_results.append((step_name, True, elapsed))
            
            print(f"\n✓ {step_name} completed in {elapsed:.1f}s")
            return True
        
        except subprocess.CalledProcessError as e:
            elapsed = time.time() - start_time
            self.step_results.append((step_name, False, elapsed))
            
            print(f"\n✗ {step_name} failed after {elapsed:.1f}s")
            print(f"Error: {e}")
            return False
    
    def print_summary(self):
        """Print pipeline execution summary."""
        print("\n" + "="*70)
        print("PIPELINE EXECUTION SUMMARY")
        print("="*70)
        
        for step_name, success, elapsed in self.step_results:
            status = "✓ PASS" if success else "✗ FAIL"
            print(f"{status} | {step_name:40s} | {elapsed:6.1f}s")
        
        total_time = sum(elapsed for _, _, elapsed in self.step_results)
        passed = sum(1 for _, success, _ in self.step_results if success)
        total = len(self.step_results)
        
        print("="*70)
        print(f"Total Steps: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {total - passed}")
        print(f"Total Time: {total_time:.1f}s")
        print("="*70)
    
    def run_pipeline(self) -> int:
        """
        Run complete integration pipeline.
        
        Returns:
            Exit code (0 = success, 1 = failure)
        """
        print("="*70)
        print("AMAZON CATALOG INTEGRATION PIPELINE")
        print("="*70)
        print(f"Project Root: {self.project_root}")
        print(f"Tools Directory: {self.tools_dir}")
        print("="*70)
        
        # Step 1: Ingest Amazon metadata
        if not self.run_step(
            "Ingest Amazon Metadata",
            self.tools_dir / "ingest_amazon_catalog.py",
            "Stream and filter Amazon JSONL files (~2,000 products)"
        ):
            print("\n❌ Pipeline failed at ingestion step")
            self.print_summary()
            return 1
        
        # Step 2: Normalize categories
        if not self.run_step(
            "Normalize Categories",
            self.tools_dir / "amazon_category_mapper.py",
            "Build consistent category hierarchy"
        ):
            print("\n❌ Pipeline failed at category normalization")
            self.print_summary()
            return 1
        
        # Step 3: Seed catalog
        if not self.run_step(
            "Seed Catalog Database",
            self.tools_dir / "seed_catalog_from_amazon.py",
            "Populate PostgreSQL with products and categories"
        ):
            print("\n❌ Pipeline failed at catalog seeding")
            self.print_summary()
            return 1
        
        # Step 4: Update latent mappings
        if not self.run_step(
            "Update Latent Item Mappings",
            self.tools_dir / "update_latent_item_mappings.py",
            "Bridge RetailRocket IDs to Amazon product UUIDs"
        ):
            print("\n❌ Pipeline failed at latent mapping update")
            self.print_summary()
            return 1
        
        # Success
        self.print_summary()
        
        print("\n" + "="*70)
        print("✓ PIPELINE COMPLETED SUCCESSFULLY")
        print("="*70)
        print("\nNext Steps:")
        print("1. Restart services: docker-compose restart")
        print("2. Run validation: python tests/test_amazon_catalog_integration.py")
        print("3. Test frontend: http://localhost:5174")
        print("="*70)
        
        return 0


def main():
    """Run pipeline orchestrator."""
    project_root = Path(__file__).parent.parent
    
    orchestrator = PipelineOrchestrator(project_root)
    exit_code = orchestrator.run_pipeline()
    
    return exit_code


if __name__ == "__main__":
    exit(main())
