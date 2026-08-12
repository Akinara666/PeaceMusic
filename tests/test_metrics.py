from __future__ import annotations

from peacemusic.core.metrics import MetricsRegistry


def test_metrics_registry_renders_counters_gauges_and_escaped_labels() -> None:
    metrics = MetricsRegistry()
    metrics.increment("peacemusic_music_play_total")
    metrics.increment(
        "peacemusic_music_play_total",
        labels={"guild_id": '1"\\\n'},
    )
    metrics.set_gauge("peacemusic_queue_size", 2)
    metrics.observe("peacemusic_agent_turn_duration_seconds", 0.25)

    rendered = metrics.render()

    assert "# TYPE peacemusic_music_play_total counter" in rendered
    assert "peacemusic_music_play_total 1" in rendered
    assert 'peacemusic_music_play_total{guild_id="1\\"\\\\\\n"} 1' in rendered
    assert "# TYPE peacemusic_queue_size gauge" in rendered
    assert "peacemusic_queue_size 2" in rendered
    assert "# TYPE peacemusic_agent_turn_duration_seconds summary" in rendered
    assert "peacemusic_agent_turn_duration_seconds_count 1" in rendered
