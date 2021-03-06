#  ------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License (MIT). See LICENSE in the repo root for license information.
#  ------------------------------------------------------------------------------------------


from pathlib import Path

import pytest

from InnerEye.Common import common_util
from InnerEye.Common.fixed_paths import DEFAULT_RESULT_IMAGE_NAME
from InnerEye.Scripts.submit_for_inference import main
from Tests.Common.test_util import DEFAULT_MODEL_ID_NUMERIC


@pytest.mark.skipif(common_util.is_windows(), reason="Testing on Linux is enough")
# Put it in the azureml set as it takes a while to run
# and we don't want to make the main set even longer.
@pytest.mark.azureml
def test_submit_for_inference() -> None:
    args = ["--image_file", "Tests/ML/test_data/train_and_test_data/id1_channel1.nii.gz",
            "--model_id", DEFAULT_MODEL_ID_NUMERIC,
            "--settings", "InnerEye/settings.yml",
            "--download_folder", "."]
    seg_path = Path(DEFAULT_RESULT_IMAGE_NAME)
    if seg_path.exists():
        seg_path.unlink()
    main(args)
    assert seg_path.exists()
