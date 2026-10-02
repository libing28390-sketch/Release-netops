"""
forecast_engine.py — Professional capacity forecasting engine.
Implements 3-Sigma outlier filtering, 7-day moving average smoothing,
linear regression fitting, R2 determination coefficient, and multi-dimensional risk scoring.
All mathematical algorithms are implemented in pure Python to maximize portability.
"""

import math
from typing import List, Tuple, Optional, Dict, Any

class BaseForecastModel:
    """Base class for forecasting models to support pluggable extensions (e.g., ARIMA, Holt-Winters)."""
    def fit_predict(self, data: List[float], steps: int) -> Tuple[List[float], Dict[str, Any]]:
        raise NotImplementedError


class LinearTrendModel(BaseForecastModel):
    """
    Linear regression model using Least Squares fitting.
    Calculates slope, intercept, and R2 (coefficient of determination).
    """
    def fit_predict(self, data: List[float], steps: int) -> Tuple[List[float], Dict[str, Any]]:
        n = len(data)
        if n < 7:
            # Insufficient data, return static forecast using the last known value
            last_val = data[-1] if n > 0 else 0.0
            return [last_val] * steps, {"slope": 0.0, "intercept": last_val, "r2": 0.0}

        # Calculate means
        x_mean = (n - 1) / 2.0
        y_mean = sum(data) / n

        # Least squares formula
        numerator = 0.0
        denominator = 0.0
        for i in range(n):
            x_diff = i - x_mean
            numerator += x_diff * (data[i] - y_mean)
            denominator += x_diff * x_diff

        slope = numerator / denominator if denominator != 0 else 0.0
        intercept = y_mean - slope * x_mean

        # Predict future steps
        predictions = []
        for i in range(steps):
            pred_val = slope * (n + i) + intercept
            # Clip between 0% and 100%
            pred_val = max(0.0, min(100.0, pred_val))
            predictions.append(round(pred_val, 2))

        # Calculate R2 (Coefficient of Determination)
        ss_res = 0.0
        ss_tot = 0.0
        for i in range(n):
            y_pred = slope * i + intercept
            ss_res += (data[i] - y_pred) ** 2
            ss_tot += (data[i] - y_mean) ** 2

        r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 1.0

        return predictions, {
            "slope": slope,
            "intercept": intercept,
            "r2": r2
        }


class ForecastEngine:
    """
    Engine to preprocess telemetry sequences and execute trend forecasting.
    """
    def __init__(self, model: BaseForecastModel = LinearTrendModel()):
        self.model = model

    @staticmethod
    def filter_outliers_3sigma(data: List[float]) -> List[float]:
        """
        Detects and smooths anomalies using the 3-Sigma rule.
        Anomalies are replaced by the average of their neighbors.
        """
        n = len(data)
        if n < 5:
            return data

        mean = sum(data) / n
        variance = sum((x - mean) ** 2 for x in data) / n
        std = math.sqrt(variance)

        if std == 0:
            return data

        cleaned = list(data)
        for i in range(n):
            if abs(data[i] - mean) > 3 * std:
                # Replace with the average of neighboring points
                left = cleaned[i - 1] if i > 0 else mean
                right = data[i + 1] if i < n - 1 else mean
                cleaned[i] = (left + right) / 2.0
        return cleaned

    @staticmethod
    def smooth_moving_average(data: List[float], window: int = 7) -> List[float]:
        """
        Applies a moving average filter.
        Uses 'valid' mode (requires 'window' elements, e.g., 36 raw points -> 30 smoothed points).
        """
        n = len(data)
        if n < window:
            return data

        smoothed = []
        for i in range(window - 1, n):
            window_sum = sum(data[i - window + 1 : i + 1])
            smoothed.append(round(window_sum / window, 2))
        return smoothed

    def predict_interface_capacity(
        self,
        history_p95: List[float],
        forecast_days: int = 30
    ) -> Dict[str, Any]:
        """
        Runs the complete pre-processing and forecast pipeline for a single interface.
        """
        if not history_p95:
            return {
                "history_raw": [],
                "history_smoothed": [],
                "predictions": [],
                "slope": 0.0,
                "r2": 0.0,
                "trend_confidence": "low",
                "days_to_80": None,
                "days_to_95": None
            }

        # 1. Outlier filtering
        filtered = self.filter_outliers_3sigma(history_p95)

        # 2. Moving average smoothing (7-day window)
        # Assumes input history length is days + 6 (e.g. 36) so output length is days (e.g. 30)
        smoothed = self.smooth_moving_average(filtered, window=7)

        # 3. Trend fitting
        predictions, stats = self.model.fit_predict(smoothed, forecast_days)

        slope = stats["slope"]
        r2 = stats["r2"]
        intercept = stats["intercept"]

        # 4. Confidence evaluation
        if r2 >= 0.6:
            confidence = "high"
        elif r2 >= 0.3:
            confidence = "medium"
        else:
            confidence = "low"

        # 5. Calculate threshold countdown (only when slope is upward and confidence is acceptable)
        days_to_80 = None
        days_to_95 = None
        current_val = smoothed[-1] if smoothed else 0.0
        n_smooth = len(smoothed)

        if slope > 0.001 and confidence != "low":
            if current_val < 80.0:
                days_to_80 = max(1, int(round((80.0 - intercept) / slope - n_smooth + 1)))
            if current_val < 95.0:
                days_to_95 = max(1, int(round((95.0 - intercept) / slope - n_smooth + 1)))

        # Slice return values to represent the exact historical range (usually 30 days)
        limit = 30
        return {
            "history_raw": [round(x, 2) for x in history_p95[-limit:]],
            "history_smoothed": [round(x, 2) for x in smoothed[-limit:]],
            "predictions": predictions,
            "slope": round(slope, 4),
            "r2": round(r2, 4),
            "trend_confidence": confidence,
            "days_to_80": days_to_80,
            "days_to_95": days_to_95
        }


def calculate_capacity_score(
    cpu_util: float,
    mem_util: float,
    intf_p95: float,
    err_count: int,
    discard_count: int,
    packet_loss_rate: float
) -> Tuple[int, str]:
    """
    Computes a multi-dimensional capacity health score (0-100) and risk level.
    Score = 100 - deductions
    """
    deductions = 0.0

    # 1. CPU Utilization (Max 30 points deduction)
    if cpu_util >= 90.0:
        deductions += 30.0
    elif cpu_util >= 80.0:
        deductions += 15.0 + (cpu_util - 80.0) * 1.5
    elif cpu_util >= 60.0:
        deductions += (cpu_util - 60.0) * 0.75

    # 2. Memory Utilization (Max 30 points deduction)
    if mem_util >= 90.0:
        deductions += 30.0
    elif mem_util >= 80.0:
        deductions += 15.0 + (mem_util - 80.0) * 1.5
    elif mem_util >= 60.0:
        deductions += (mem_util - 60.0) * 0.75

    # 3. Interface P95 Utilization (Max 40 points deduction)
    if intf_p95 >= 95.0:
        deductions += 40.0
    elif intf_p95 >= 80.0:
        deductions += 20.0 + (intf_p95 - 80.0) * 1.33
    elif intf_p95 >= 60.0:
        deductions += (intf_p95 - 60.0) * 1.0

    # 4. Errors & Discards (Max 20 points deduction)
    # Packet loss rate deduction
    if packet_loss_rate > 0.01:  # Greater than 1%
        deductions += min(10.0, 5.0 + (packet_loss_rate - 0.01) * 200.0)
    # Errors count deduction
    if err_count > 1000:
        deductions += min(10.0, 5.0 + (err_count - 1000) / 1000.0)

    score = max(0, min(100, int(round(100.0 - deductions))))

    # Map score to risk levels
    if score >= 90:
        risk = "healthy"
    elif score >= 70:
        risk = "warning"
    elif score >= 50:
        risk = "high"
    else:
        risk = "critical"

    return score, risk
