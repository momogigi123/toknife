# -*- coding: utf-8 -*-
"""adaptive_aggregator.py — 自適應聚合器（v5.3 開源版）

對工具輸出的數據列表做 Top-N + 異常檢測 + 統計摘要，
支援校準模式（calibrated）根據數據分佈動態調整閾值。

用法:
  from adaptive_aggregator import AdaptiveAggregator
  agg = AdaptiveAggregator()
  agg.calibrate(data)
  result = agg.aggregate(data, sort_by="value", top_n=5, calibrated=True)
"""
import statistics


class AdaptiveAggregator:
    """自適應聚合器：Top-N + 異常檢測 + 統計摘要。"""

    def __init__(self, iqr_multiplier=1.5, anomaly_ratio_threshold=0.1):
        self.iqr_multiplier = iqr_multiplier
        self.anomaly_ratio_threshold = anomaly_ratio_threshold
        self._calibrated = False
        self._q1 = None
        self._q3 = None
        self._iqr = None
        self._median = None
        self._mean = None
        self._std = None

    def _to_number(self, v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def calibrate(self, data, sort_by=None):
        """根據數據分佈校準閾值。"""
        if not isinstance(data, list) or not data:
            return
        # 自動找數值字段
        if not sort_by:
            for k, v in data[0].items():
                if self._to_number(v) is not None:
                    sort_by = k
                    break
        if not sort_by:
            return
        values = [self._to_number(row.get(sort_by)) for row in data
                  if self._to_number(row.get(sort_by)) is not None]
        if len(values) < 4:
            return
        values_sorted = sorted(values)
        n = len(values_sorted)
        self._q1 = values_sorted[n // 4]
        self._q3 = values_sorted[(3 * n) // 4]
        self._iqr = self._q3 - self._q1
        self._median = values_sorted[n // 2]
        self._mean = statistics.mean(values)
        self._std = statistics.stdev(values) if len(values) > 1 else 0
        self._calibrated = True

    def _detect_anomalies(self, data, sort_by):
        """IQR 方法檢測異常值。"""
        if not self._calibrated or self._iqr == 0:
            return []
        low = self._q1 - self.iqr_multiplier * self._iqr
        high = self._q3 + self.iqr_multiplier * self._iqr
        anomalies = []
        for row in data:
            v = self._to_number(row.get(sort_by))
            if v is None:
                continue
            if v < low or v > high or (self._median and v > self._median * 10):
                anomalies.append(row)
        return anomalies

    def aggregate(self, data, sort_by=None, top_n=5, calibrated=False):
        """聚合數據：Top-N + 異常 + 統計摘要。

        Args:
            data: list of dict
            sort_by: 排序字段
            top_n: 返回前 N 條
            calibrated: 是否使用校準後的閾值

        Returns:
            dict: {top_n, anomalies, summary, total}
        """
        if not isinstance(data, list) or not data:
            return {"top_n": [], "anomalies": [], "summary": {}, "total": 0}

        # 自動找數值字段
        if not sort_by:
            for k, v in data[0].items():
                if self._to_number(v) is not None:
                    sort_by = k
                    break
        if not sort_by:
            return {"top_n": data[:top_n], "anomalies": [],
                    "summary": {"count": len(data)}, "total": len(data)}

        if calibrated and not self._calibrated:
            self.calibrate(data, sort_by)

        # 異常檢測
        anomalies = self._detect_anomalies(data, sort_by) if calibrated else []

        # 排除異常後的 Top-N
        normal_data = [row for row in data if row not in anomalies]
        if not normal_data:
            normal_data = data
        sorted_data = sorted(normal_data,
                             key=lambda x: self._to_number(x.get(sort_by, 0)) or 0,
                             reverse=True)
        top = sorted_data[:top_n]

        # 統計摘要
        values = [self._to_number(row.get(sort_by)) for row in data
                  if self._to_number(row.get(sort_by)) is not None]
        summary = {
            "count": len(data),
            "mean": round(statistics.mean(values), 2) if values else 0,
            "median": round(statistics.median(values), 2) if values else 0,
            "max": max(values) if values else 0,
            "min": min(values) if values else 0,
            "anomaly_count": len(anomalies),
        }

        return {
            "top_n": top,
            "anomalies": anomalies,
            "summary": summary,
            "total": len(data),
            "sort_by": sort_by,
        }
