"""``labels template|review|apply|finalize|reopen DATASET``: label files of an exported dataset (RF11, RF12)."""

import argparse
import json
import sys
from pathlib import Path

from mri_dataset_tool.application.services.dataset_build import (
    InvalidBuildInput,
    check_classes,
    is_exported_dataset,
    label_defects,
)
from mri_dataset_tool.application.services.labels import (
    apply_label_corrections,
    finalize_labels,
    reopen_labels,
    review_labels,
    write_label_template,
)
from mri_dataset_tool.presentation.cli._common import EXIT_FAILED, EXIT_OK, EXIT_USAGE, add_command


def add_parser(subparsers) -> None:
    parser = add_command(
        subparsers,
        "labels",
        help="plantilla, revisión y corrección de etiquetas",
        description="Etiquetas por participante/sesión de un dataset exportado (labels.tsv, labels.json). "
        "Flujo: template, apply (correcciones), review, finalize; reopen deshace finalize.",
    )
    actions = parser.add_subparsers(dest="action", title="acciones", metavar="ACCION", required=True)
    template = add_command(actions, "template", help="escribe la plantilla sin etiquetar")
    template.add_argument("--classes", nargs="+", required=True, metavar="NAME[=DESCRIPTION]", help="clases")
    review = add_command(actions, "review", help="muestra los defectos de la tabla (solo conteos)")
    review.add_argument("--json", action="store_true", help="salida en JSON")
    apply = add_command(actions, "apply", help="aplica un TSV de correcciones (columnas de labels.tsv)")
    apply.add_argument("--corrections", type=Path, required=True, help="TSV de correcciones")
    finalize = add_command(actions, "finalize", help="cierra las etiquetas (exige la tabla completa)")
    reopen = add_command(actions, "reopen", help="reabre unas etiquetas cerradas")
    for action in (template, review, apply, finalize, reopen):
        action.add_argument("dataset", type=Path, help="raíz del dataset BIDS exportado")
        action.set_defaults(run=run)


def _review(dataset: Path, as_json: bool) -> None:
    review = review_labels(dataset)
    result = {
        "dataset_pairs": review.dataset_pairs,
        "labeled": review.labeled,
        "class_counts": review.class_counts,
        "defects": label_defects(review),  # counts by fixed code, never ids
        "complete": review.is_complete,
    }
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    print(f"Pairs: {review.dataset_pairs}  labeled: {review.labeled}  classes: {review.class_counts}")
    print(f"Defects: {result['defects'] or 'none'}")
    print(f"Complete: {'yes' if review.is_complete else 'no'}")


def run(args: argparse.Namespace) -> int:
    dataset = args.dataset
    errors = sys.stderr if getattr(args, "json", False) else sys.stdout  # --json: stdout holds only JSON
    if not dataset.is_dir():
        print("Dataset directory not found.", file=errors)
        return EXIT_USAGE
    if not is_exported_dataset(dataset):  # never write label files (source ids) into a raw input
        print("Not a dataset exported by this tool.", file=errors)
        return EXIT_USAGE
    classes = None
    if args.action == "template":
        try:
            classes = check_classes(args.classes)
        except InvalidBuildInput as error:  # fixed text
            print(error)
            return EXIT_USAGE
    if args.action == "apply" and not args.corrections.is_file():
        print("Corrections file not found.")
        return EXIT_USAGE

    try:
        if args.action == "template":
            write_label_template(dataset, classes)
            print(f"Label template written ({len(classes)} classes).")
        elif args.action == "review":
            _review(dataset, args.json)
        elif args.action == "apply":
            print(f"Label corrections applied: {apply_label_corrections(dataset, args.corrections)}")
        elif args.action == "finalize":
            finalize_labels(dataset)
            print("Labels finalized.")
        else:
            reopen_labels(dataset)
            print("Labels reopened.")
    except Exception as error:  # fixed messages, but only the type is shown
        print(f"Labels {args.action} failed: {type(error).__name__}", file=errors)
        return EXIT_FAILED
    return EXIT_OK
