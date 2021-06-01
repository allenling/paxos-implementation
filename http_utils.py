
from http.server import HTTPServer, BaseHTTPRequestHandler
import cgi
import json


class JsonDispatchHandler(BaseHTTPRequestHandler):


    def _set_headers(self, code=200):
        self.send_response(code)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        return

    def do_POST(self):
        ctype, _ = cgi.parse_header(self.headers.get('content-type'))
        if ctype != 'application/json':
            self.send_response(400)
            self.end_headers()
            return
        length = int(self.headers.get('content-length'))
        data = self.rfile.read(length)
        message = json.loads(data.decode())
        if "*" in self.server.user_paths:
            func = self.server.user_paths["*"]
            res_dict = func(self.path[1:], message)
            res_dict = {} if res_dict is None else res_dict
            self._set_headers()
            self.wfile.write(json.dumps(res_dict).encode("utf-8"))
        else:
            func = self.server.user_paths.get(self.path[1:], None)
            if func:
                res_dict = func(message)
                if res_dict:
                    self._set_headers()
                    self.wfile.write(json.dumps(res_dict).encode("utf-8"))
                else:
                    self.send_response(400)
                    self.end_headers()
            else:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "no such method"}).encode("utf-8"))
        return


class DispatchServer(HTTPServer):

    def __init__(self, name, port=8080):
        self.name = name
        self.port = port
        self.user_paths = {}
        super(HTTPServer, self).__init__(("", port), JsonDispatchHandler)
        return

    def set_path(self, path, func):
        self.user_paths[path] = func
        return

    def start(self):
        print('Starting httpd %s on port %d...' % (self.name, self.port))
        self.serve_forever()
        return




def main():
    j = DispatchServer("disptach_test", 8081)

    def pong_func(msg):
        print("get msg %s" % msg)
        return {"status": "success"}
    j.set_path("pong", pong_func)
    j.start()
    return

if __name__ == "__main__":
    main()