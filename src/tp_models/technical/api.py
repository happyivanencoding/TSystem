from flask import Flask, jsonify, Response
import subprocess
import sys

app = Flask(__name__)

@app.route("/health/ready")
def health():
    return "Healthy"

@app.route("/version")
def version():
    return "Healthy_20_01.02"

@app.route('/run', methods=['POST'])
def run_main():
    try:
        process = subprocess.Popen(
        [sys.executable, "-u", "-m", "tp_models.technical.Main"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1)

        def generate():
            for line in process.stdout:
                # print(line.strip())
                sys.stdout.flush()  # force l'affichage immédiat
                yield line  # envoie chaque ligne au client
            process.wait()

        return Response(generate(), mimetype='text/plain')
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)

