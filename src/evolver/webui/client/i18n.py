"""Multi-language support for the WebUI dashboard.

Renders a small i18n dictionary and lookup helper as inline JS.
Currently supports: English (en), Simplified Chinese (zh-Hans).
"""

from __future__ import annotations

I18N_DICTIONARY = {
    "en": {
        "status": "Status",
        "assets": "Assets",
        "recent_events": "Recent Events",
        "genes": "Genes",
        "capsules": "Capsules",
        "healthy": "Healthy",
        "warning": "Warning",
        "critical": "Critical",
        "unknown": "Unknown",
    },
    "zh-Hans": {
        "status": "状态",
        "assets": "资产",
        "recent_events": "最近事件",
        "genes": "基因",
        "capsules": "胶囊",
        "healthy": "健康",
        "warning": "警告",
        "critical": "严重",
        "unknown": "未知",
    },
}


I18N_JS = (
    """
(function() {
  'use strict';
  window.EvolverI18n = window.EvolverI18n || {};
  const I = window.EvolverI18n;

  I.dict = """
    + str(I18N_DICTIONARY).replace("'", '"')
    + """;
  I.lang = navigator.language.startsWith('zh') ? 'zh-Hans' : 'en';

  I.t = function(key) {
    return (I.dict[I.lang] && I.dict[I.lang][key]) || key;
  };
})();
"""
)
