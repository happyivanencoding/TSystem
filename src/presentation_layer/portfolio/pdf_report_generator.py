"""Portfolio dashboard PDF report generation."""
"""
Extension PDF pour PortfolioDashboard
Génération de rapport PDF à partir du fichier Excel de sortie
"""

import os
import time
import xlwings as xw
from PIL import ImageGrab, Image as PILImage

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Image as RLImage, Spacer,
                                     PageBreak, Paragraph, Table, TableStyle)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except ImportError:  # reportlab is optional for dashboard import smoke tests.
    A4 = mm = SimpleDocTemplate = RLImage = Spacer = PageBreak = Paragraph = Table = TableStyle = None
    getSampleStyleSheet = ParagraphStyle = TA_CENTER = TA_LEFT = colors = None
    REPORTLAB_AVAILABLE = False
from datetime import datetime


# =========================================================================
# Configuration par défaut
# =========================================================================
DEFAULT_SHEET_CONFIGS = [
    {
        "name": "Analyse",
        "columns": 2,
        "captures": [
            {"range": "A1:F20",   "label": "Déviation Sectorielle"},
            {"range": "O1:S4",    "label": "Principales Métriques"},
            {"range": "G1:J36",   "label": "Déviation Métrique"},
            {"range": "K1:N30",   "label": "Répartition des Styles Actions"},
            {"range": "A43:F47",  "label": "Déviation Géographique"},
            {"range": "A49:F54",  "label": "Exposition Market Cap"},
            {"range": "A56:F79",  "label": "Répartition Pays"},
            {"range": "G65:I71",  "label": "Top 5 Sous-exposition"},
            {"range": "K65:M71",  "label": "Top 5 Sur-exposition"},
            {"range": "G74:J80",  "label": "Titre Hors Indice"},
            {"range": "G82:I87",  "label": "Warning selon Score IA"},
            {"range": "A81:C100", "label": "Contribution TE Sectorielle"},
            {"range": "G89:L99",  "label": "Top Contrib TE"},

            # Partie Graphe
            {"range": "P6:W25",    "label": "Exposition Sectorielle"},
            {"range": "P26:W45",   "label": "Beta Sectoriel"},
            {"range": "P46:W63",   "label": "Répartition Pays"},
            {"range": "X6:AD21",   "label": "Comparaison Score IA"},
            {"range": "X22:AD36",  "label": "Exposition Top Facteurs"},
            {"range": "X37:AD51",  "label": "Exposition Worst Facteurs"},
            {"range": "AE6:AK21",  "label": "Exposition Recommandation Analyst"},
            {"range": "AE22:AK36", "label": "Exposition Facteurs"},
        ]
    },
    {
        "name": "TopWorst Perf",
        "columns": 1,
        "captures": [
            {"range": "C1:J15",  "label": "Top 10 Performers Fonds"},
            {"range": "L1:S15",  "label": "Worst 10 Performers Fonds"},
            {"range": "C17:J37", "label": "Top 20 Performers Benchmark"},
            {"range": "L17:S37", "label": "Worst 20 Performers Benchmark"},
        ]
    }
]


# =========================================================================
# Fonction principale
# =========================================================================

def generate_pdf_report(
    excel_path: str,
    pdf_path: str = None,
    sheet_configs: list = None,
):
    """
    Génère un rapport PDF compact à partir d'un fichier Excel via xlwings.

    Paramètres:
        excel_path (str)    : Chemin du fichier Excel source
        pdf_path (str)      : Chemin du PDF de sortie
                              (si None, remplace .xlsx par .pdf)
        sheet_configs (list): Liste de configurations de sheets.
            Format:
            [
                {
                    "name": "Analyse",      # Nom exact du sheet Excel
                    "columns": 2,           # Disposition : 1, 2 ou 3 colonnes
                    "captures": [
                        {"range": "B1:F20", "label": "Déviation Sectorielle"},
                    ]
                },
            ]

    Retourne:
        str: Chemin du PDF généré
    """
    if not REPORTLAB_AVAILABLE:
        raise ImportError("reportlab is required to generate PDF reports. Install the web/report optional dependencies first.")

    if pdf_path is None:
        pdf_path = excel_path.replace(".xlsx", ".pdf")

    if sheet_configs is None:
        sheet_configs = DEFAULT_SHEET_CONFIGS

    for cfg in sheet_configs:
        cols = cfg.get("columns", 2)
        if cols not in (1, 2, 3):
            raise ValueError(
                f"Sheet '{cfg['name']}': columns={cols} invalide. "
                "Valeurs acceptées : 1, 2 ou 3."
            )

    print(f"📄 Génération du rapport PDF...")
    print(f"   Excel source : {os.path.basename(excel_path)}")
    print(f"   PDF cible    : {os.path.basename(pdf_path)}")
    print()
    for cfg in sheet_configs:
        print(f"   [{cfg['name']}]  {cfg.get('columns', 2)} colonne(s) "
              f"— {len(cfg.get('captures', []))} capture(s)")

    images_data = _capture_with_xlwings(excel_path, sheet_configs)
    _build_compact_pdf(pdf_path, images_data, sheet_configs)

    print(f"\n✅ Rapport PDF généré : {pdf_path}")
    return pdf_path


# =========================================================================
# Capture via xlwings
# =========================================================================

def _capture_with_xlwings(excel_path: str, configs: list) -> list:
    """Capture chaque range Excel en image PNG via xlwings."""
    print("\n   📸 Capture des ranges via xlwings...")

    app = xw.App(visible=False)
    wb  = app.books.open(excel_path)
    time.sleep(2)
    images_data = []

    try:
        for config in configs:
            sheet_name = config["name"]
            columns    = config.get("columns", 2)
            print(f"      → {sheet_name}  ({columns} col.)")

            if sheet_name not in [s.name for s in wb.sheets]:
                print(f"         ⚠️  Sheet introuvable, ignoré")
                continue

            ws = wb.sheets[sheet_name]

            for idx, capture in enumerate(config.get("captures", [])):
                range_addr = capture["range"]
                label      = capture.get("label", range_addr)
                safe_name  = range_addr.replace(":", "_")
                img_path   = f"temp_{sheet_name}_{idx}_{safe_name}.png"

                try:
                    ws.range(range_addr).api.CopyPicture(Format=2)
                    time.sleep(0.5)
                    img = ImageGrab.grabclipboard()
                    if img:
                        img.save(img_path, "PNG")
                        with PILImage.open(img_path) as pil_img:
                            img_width, img_height = pil_img.size
                        images_data.append({
                            "path":       img_path,
                            "label":      label,
                            "sheet":      sheet_name,
                            "columns":    columns,
                            "img_width":  img_width,
                            "img_height": img_height,
                        })
                        print(f"         ✓ {label}  ({range_addr})  [{img_width}x{img_height}px]")
                    else:
                        print(f"         ✗ Clipboard vide pour {range_addr}")
                except Exception as e:
                    print(f"         ✗ Erreur sur {range_addr}: {e}")
    finally:
        wb.close()
        app.quit()

    return images_data


# =========================================================================
# Assemblage PDF — sans KeepTogether
# =========================================================================

def _build_compact_pdf(pdf_path: str, images_data: list, configs: list):
    """
    Assemble les images en PDF compact avec mise en page multi-colonnes.
    Images et légendes sont dans des rangées séparées du tableau
    pour éviter le LayoutError causé par KeepTogether sur de grandes images.
    """
    print("\n   📋 Assemblage du PDF...")

    PAGE_W, PAGE_H = A4
    L_MARGIN = R_MARGIN = 10 * mm
    T_MARGIN = 15 * mm
    B_MARGIN = 10 * mm
    USABLE_W = PAGE_W - L_MARGIN - R_MARGIN
    USABLE_H = PAGE_H - T_MARGIN - B_MARGIN
    COL_GAP  = 5 * mm

    # Limite de hauteur : 50% de la hauteur utilisable
    MAX_IMG_HEIGHT = USABLE_H * 0.50

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        leftMargin=L_MARGIN,
        rightMargin=R_MARGIN,
        topMargin=T_MARGIN,
        bottomMargin=B_MARGIN,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=14,
        textColor=colors.HexColor("#21808D"),
        spaceAfter=4,
        alignment=TA_LEFT,
    )
    date_style = ParagraphStyle(
        "ReportDate",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#626C71"),
        spaceAfter=10,
    )
    section_style = ParagraphStyle(
        "SectionTitle",
        parent=styles["Heading2"],
        fontSize=11,
        textColor=colors.HexColor("#21808D"),
        spaceBefore=6,
        spaceAfter=4,
    )
    caption_style = ParagraphStyle(
        "Caption",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#626C71"),
        spaceAfter=2,
        alignment=TA_CENTER,
    )

    story = []

    # En-tête sur la première page (pas de page blanche)
    story.append(Paragraph("Rapport de Gestion Actions", title_style))
    story.append(Paragraph(
        f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}",
        date_style
    ))

    # Regroupement des images par sheet
    sheet_order = [cfg["name"] for cfg in configs]
    grouped = {name: [] for name in sheet_order}
    for img in images_data:
        if img["sheet"] in grouped:
            grouped[img["sheet"]].append(img)

    first_section = True
    for sheet_name in sheet_order:
        imgs = grouped.get(sheet_name, [])
        if not imgs:
            continue

        if not first_section:
            story.append(PageBreak())
        first_section = False

        story.append(Paragraph(sheet_name, section_style))
        story.append(Spacer(1, 3 * mm))

        n_cols = imgs[0].get("columns", 2)
        col_w  = (USABLE_W - COL_GAP * (n_cols - 1)) / n_cols

        # Construction des rangées : images d'abord, légendes en dessous
        # Structure : [img_row_1, cap_row_1, img_row_2, cap_row_2, ...]
        all_rows = []

        for i in range(0, len(imgs), n_cols):
            batch     = imgs[i: i + n_cols]
            img_cells = []
            cap_cells = []

            for img_data in batch:
                if not os.path.exists(img_data["path"]):
                    img_cells.append(
                        Paragraph(f"[Image manquante: {img_data['label']}]", caption_style)
                    )
                    cap_cells.append("")
                    continue

                original_w   = img_data["img_width"]
                original_h   = img_data["img_height"]
                aspect_ratio = original_h / original_w if original_w > 0 else 1.0

                natural_height = col_w * aspect_ratio
                if natural_height > MAX_IMG_HEIGHT:
                    img_h = MAX_IMG_HEIGHT
                    img_w = img_h / aspect_ratio   # largeur réduite proportionnellement
                else:
                    img_h = natural_height
                    img_w = col_w

                img_cells.append(RLImage(img_data["path"], width=img_w, height=img_h))
                cap_cells.append(Paragraph(img_data["label"], caption_style))

            # Compléter la dernière ligne si elle est incomplète
            while len(img_cells) < n_cols:
                img_cells.append("")
                cap_cells.append("")

            # Composition de légende et l'image (légende first, image after)
            all_rows.append(cap_cells)   # rangée légendes
            all_rows.append(img_cells)   # rangée images
            

        # Tableau sans KeepTogether → ReportLab peut découper entre les rangées
        tbl = Table(all_rows, colWidths=[col_w] * n_cols)
        tbl.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), COL_GAP),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ]))
        story.append(tbl)

    doc.build(story)

    # Nettoyage des fichiers temporaires
    for img_data in images_data:
        if os.path.exists(img_data["path"]):
            os.remove(img_data["path"])
    print("   🧹 Fichiers temporaires supprimés")


# =========================================================================
# Injection dans PortfolioDashboard
# =========================================================================

def add_pdf_generation_to_dashboard():
    """
    Retourne la méthode à injecter dans PortfolioDashboard.

    Dans portfolio_dashboard.py :
        from pdf_report_generator import add_pdf_generation_to_dashboard
        PortfolioDashboard.generate_pdf_report = add_pdf_generation_to_dashboard()
    """

    def generate_pdf_report_method(self,
                                   pdf_path: str = None,
                                   sheet_configs: list = None):
        """
        Génère un rapport PDF compact à partir du fichier Excel de sortie.
        Nécessite que export_to_excel() ait été appelé au préalable.

        Paramètres:
            pdf_path (str)      : Chemin personnalisé pour le PDF
            sheet_configs (list): Voir generate_pdf_report() pour le format

        Exemple:
            dashboard.generate_pdf_report(
                sheet_configs=[
                    {
                        "name": "Analyse",
                        "columns": 2,
                        "captures": [
                            {"range": "B1:F20",  "label": "Déviation Sectorielle"},
                            {"range": "H1:J36",  "label": "Déviation Métrique"},
                            {"range": "L1:N30",  "label": "Répartition Styles"},
                            {"range": "P1:S4",   "label": "Métriques"},
                        ]
                    },
                    {
                        "name": "TopWorst Perf",
                        "columns": 1,
                        "captures": [
                            {"range": "C1:S40", "label": "Top & Worst Performers"},
                        ]
                    }
                ]
            )
        """
        if not os.path.exists(self.path_output):
            raise FileNotFoundError(
                f"Le fichier Excel n'existe pas : {self.path_output}\n"
                "Veuillez d'abord appeler export_to_excel()"
            )

        result_path = generate_pdf_report(
            excel_path=self.path_output,
            pdf_path=pdf_path,
            sheet_configs=sheet_configs,
        )
        self.pdf_report_path = result_path
        return result_path

    return generate_pdf_report_method
