from application_bootstrap_proof import configuration, sources


def test_actual_bootstrap_configuration_and_source_closure():
    value = configuration()
    assert value.detectors[0].identity.mode == "continuous"
    assert value.detectors[0].detection.interval == 9
    assert value.detectors[0].detection.frame_retention == 1
    assert value.detectors[1].yolo is None
    assert value.detectors[1].detection.source == ("1",)
    paths = {str(p) for p in sources()}
    assert {
        "detector/src/aidetector/bootstrap.py",
        "detector/src/aidetector/adapters/identity_profile_collector.py",
        "detector/src/aidetector/adapters/identity_profiles.py",
        "detector/src/aidetector/adapters/inference/continuous_identity.py",
    } <= paths
