"""Modeles de configuration utilises par l'application."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AppInfoSettings:
    """Parametres generaux de l'application."""

    application_name: str = "Backtest Code"
    default_user: str = "user1"
    default_mode: str = "research"
    auto_open_plot: bool = False


@dataclass
class UserSettings:
    """Informations liees a l'utilisateur courant."""

    name: str = "user1"


@dataclass
class PathSettings:
    """Chemins d'entree et de sortie."""

    screen: str = ""
    returns: str = ""
    liste_noire: str = ""
    output_dir: str = ""
    score_pivot_esg_path: str = ""


@dataclass
class RunSettings:
    """Configuration principale d'un run simple."""

    mode: str = "research"
    ptf_name: str = "PTF TEST"
    bench: str = ""
    metrics: list[str] = field(default_factory=list)
    percentile: float = 0.2
    top: bool = True
    ponderation: str = "Racine cube"
    esg_exclusion: float = 0.2
    cut_mkt_cap: float = 0.0
    reco_secto: list[float] = field(default_factory=lambda: [0.0] * 19)
    reco_facto: list[float] = field(default_factory=lambda: [0.0] * 5)
    score_neutral: str = "ICB 19"
    weight_neutral: str = "ICB 19"
    top_mandatory: int | None = None
    cap_weight_threshold: float | None = None
    score_pivot_esg: str | float | None = None
    mode_monthly_prod: bool = False
    start_date: str = ""
    freq_rebal: int | None = None
    screen_start_date: str = "mois_impair"
    fill_method: str = "drift"
    max_weight: float = 1.0
    sector_neutral: bool = False


@dataclass
class BatchSettings:
    """Configuration d'un batch de runs."""

    benches: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    percentiles: list[float] = field(default_factory=list)
    start_dates: list[str] = field(default_factory=list)
    top_values: list[bool] = field(default_factory=list)


@dataclass
class AppSettings:
    """Objet racine de configuration."""

    app: AppInfoSettings = field(default_factory=AppInfoSettings)
    user: UserSettings = field(default_factory=UserSettings)
    paths: PathSettings = field(default_factory=PathSettings)
    run: RunSettings = field(default_factory=RunSettings)
    batch: BatchSettings = field(default_factory=BatchSettings)

    def to_dict(self) -> dict[str, Any]:
        """Retourne une representation serialisable."""

        return asdict(self)

    def copy(self) -> "AppSettings":
        """Produit une copie complete de l'objet."""

        return AppSettings.from_dict(self.to_dict())

    @classmethod
    def from_dict(cls, raw_data: dict[str, Any] | None) -> "AppSettings":
        """Construit un objet de configuration a partir d'un dictionnaire."""

        raw_data = raw_data or {}
        return cls(
            app=AppInfoSettings(**raw_data.get("app", {})),
            user=UserSettings(**raw_data.get("user", {})),
            paths=PathSettings(**raw_data.get("paths", {})),
            run=RunSettings(**raw_data.get("run", {})),
            batch=BatchSettings(**raw_data.get("batch", {})),
        )
