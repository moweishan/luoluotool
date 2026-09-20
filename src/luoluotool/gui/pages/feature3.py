"""功能三预留配置页：启用开关 + 规划中说明（共用基类见 planned_feature）。"""

from luoluotool.config.models import AppConfig, FeatureConfig
from luoluotool.gui.pages.planned_feature import PlannedFeaturePage


class Feature3Page(PlannedFeaturePage):
    """绑定 features.feature_3.enabled。"""

    title = "功能三"

    def _feature(self, config: AppConfig) -> FeatureConfig:
        return config.features.feature_3
