from lien_import import deliverables
from lien_import.config import AppConfig


def test_discovery_summary_markdown(tmp_path, data_dir):
    md = deliverables.discovery_summary("TN", str(data_dir))
    assert md.startswith("# Deliverable A - Discovery Summary (TN)")
    assert "## Signature" in md
    assert "tnu_combined" in md and "tnu_starter" in md
    # ATT/ESS file under a TN run -> unmapped section
    assert "UNMAPPED" in md
    assert "Proposed mapping to `liens`" in md


def test_preview_audit_results_markdown(tmp_path, combined_state_csv):
    cfg = AppConfig()
    cfg.output_dir = tmp_path
    md = deliverables.preview_audit_results("TN", str(combined_state_csv), cfg)
    assert md.startswith("# Deliverable C - Preview / Audit Results (TN)")
    assert "Reconciles: **True**" in md
    assert "| would insert | 22 |" in md
    assert "Cross-tab" in md
    assert "Representative classified examples" in md
