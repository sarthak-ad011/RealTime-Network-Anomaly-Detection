set -euo pipefail
DATA_DIR="${DATA_DIR:-data/raw}"
mkdir -p "$DATA_DIR"
URL="http://cicresearch.ca/CICDataset/CIC-IDS-2017/Dataset/CIC-IDS-2017/CSVs/MachineLearningCSV.zip"
if [ ! -f "$DATA_DIR/MachineLearningCSV.zip" ]; then
  echo "Downloading..."
  curl -L -o "$DATA_DIR/MachineLearningCSV.zip" "$URL"
fi
unzip -o "$DATA_DIR/MachineLearningCSV.zip" -d "$DATA_DIR"
echo "Done. CSVs:"; ls -lh "$DATA_DIR"/*.csv 2>/dev/null || true