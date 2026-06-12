from enum import StrEnum


class MarketRegime(StrEnum):
    BULL_TREND = "BULL_TREND"
    BEAR_TREND = "BEAR_TREND"
    HIGH_VOL = "HIGH_VOL"
    LOW_VOL_RANGE = "LOW_VOL_RANGE"
    CRISIS = "CRISIS"


class Strategy(StrEnum):
    MOMENTUM = "MOMENTUM"
    MEAN_REVERSION = "MEAN_REVERSION"
    SECTOR_ROTATION = "SECTOR_ROTATION"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class OperatingMode(StrEnum):
    SEMI_AUTO = "SEMI_AUTO"
    FULL_AUTO = "FULL_AUTO"


class CycleOutcome(StrEnum):
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"


class SessionOutcome(StrEnum):
    CLEAN = "clean"
    LOSS_LIMIT = "loss_limit"
    KILLED = "killed"
    TIMED_OUT = "timed_out"


class DebateWinner(StrEnum):
    OPTIMIST = "optimist"
    PESSIMIST = "pessimist"
    TIE = "tie"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class HITLAction(StrEnum):
    CONFIRM = "confirm"
    ABORT = "abort"
    TIMEOUT = "timeout"


class SessionTimeframe(StrEnum):
    MIN_30 = "30Min"
    HOUR_1 = "1Hour"
    HOUR_3 = "3Hour"
    HOUR_12 = "12Hour"
    DAY_1 = "1Day"
    DAY_2 = "2Day"
    DAY_5 = "5Day"
