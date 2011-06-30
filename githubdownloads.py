import os

import base64
from io import BytesIO
import json
import random
import urllib2

__all__ = ["Downloads"]

GITHUB_API = "https://api.github.com/repos/%s/downloads"

class MethodRequest(urllib2.Request):
    def get_method(self):
        if hasattr(self, "method") and self.method:
            return self.method
        return urllib2.Request.get_method(self)


class S3Multipart(object):
    boundary = "ghd%16.16x" % random.randint(0, 1<<64)

    def __init__(self, j, file_data):
        self.data = BytesIO()
        self.add_field("key", j["path"])
        self.add_field("acl", j["acl"])
        self.add_field("success_action_status", "201")
        self.add_field("Filename", j["name"])
        self.add_field("AWSAccessKeyId", j["accesskeyid"])
        self.add_field("Policy", j["policy"])
        self.add_field("Signature", j["signature"])
        self.add_field("Content-Type", j["mime_type"])
        self.add_file("file", j["name"], j["mime_type"], file_data)
        self.data.write("--" + self.boundary + "--\r\n\r\n")
        self.data.seek(0,0)

    def add_field(self, key, value):
        self.data.write("--" + self.boundary)
        self.data.write("\r\n")
        self.data.write('Content-Disposition: form-data; name="%s"'
                        % str(key)
                        )
        self.data.write("\r\n")
        self.data.write("\r\n")
        self.data.write(str(value))
        self.data.write("\r\n")

    def add_file(self, key, file_name, mime, value):
        self.data.write("--" + self.boundary)
        self.data.write("\r\n")
        self.data.write('Content-Disposition: form-data; name="%s"; filename="%s"'
                        % (str(key), str(file_name))
                        )
        self.data.write("\r\n")
        self.data.write('Content-Type: %s' % str(mime))
        self.data.write("\r\n")
        self.data.write("\r\n")
        self.data.write(value)
        self.data.write("\r\n")

class DownloadsException(Exception):
    pass

class DownloadInfo(object):
    def __init__(self, owner, data):
        self.owner = owner
        for x in ["description", "download_count", "size", "name", "id"]:
            if x in data:
                setattr(self, x, data[x])
        self.api_url = data["url"]
        self.download_url = data["html_url"]

    def __repr__(self):
        return "%s (%d)" % (self.name, self.id)

    def delete(self):
        self.owner.delete(self.id)

class Downloads(object):
    def __init__(self, repo, user, password, debug=0):
        self.repo = repo
        self.user = user
        self.password = password

        self.api = GITHUB_API % (repo)

        raw = "%s:%s" % (user, password)
        self.auth = 'Basic %s' % base64.b64encode(raw).strip()

        https_handler = urllib2.HTTPSHandler(debuglevel=debug)
        self.opener = urllib2.build_opener(https_handler)

    def _request(self, additional_path=None, data=None, headers={}, method=None):
        api = self.api
        if additional_path:
            api += additional_path
        headers['Authorization'] = self.auth
        req = MethodRequest(url=api, data=data, headers=headers)
        if method:
            req.method = method
        return self.opener.open(req)

    def list(self):
        return [DownloadInfo(self, i) for i in json.load(self._request())]

    def delete(self, id_or_name):
        if not isinstance(id_or_name, int):
            self.delete(self.get_info_by_name(id_or_name).id)
            return
        self._request(additional_path=("/%d" % id_or_name), method="DELETE")


    def get_info_by_id(self, id):
        j = json.load(self._request(additional_path=("/%d" % id)))
        return DownloadInfo(j)

    def get_info_by_name(self, name):
        for d in self.list():
            if d.name == name:
                return d
        raise DownloadsException("no download with that name")


    def upload(self, file_or_name, file_name=None, mime=None, replace=False):
        if isinstance(file_or_name, basestring):
            fo = open(file_or_name, "rb")
            try:
                io = BytesIO(fo.read())
            finally:
                fo.close()
            return self.upload(io,
                               file_name or os.path.basename(file_or_name),
                               mime=mime,
                               replace=replace
                               )

        if not file_name:
            raise DownloadsException("Must provide a file name")

        data = file_or_name.read()
        data_len = len(data)

        j = {"name": file_name,
             "size": data_len
             }
        if mime:
            j["content_type"] = mime

        j = json.dumps(j)
        try:
            req = self._request(data=j)
        except urllib2.HTTPError,ex:
            if not replace:
                raise

            j = json.load(ex)
            for e in j["errors"]:
                if e["code"] == "already_exists":
                    self.delete(file_name)
                    return self.upload(
                                       BytesIO(data),
                                       file_name,
                                       mime=mime,
                                       replace=False)
            raise

        j = json.load(req)
        rv = DownloadInfo(self, j)
        data = S3Multipart(j, data).data
        datalen = len(data.getvalue())
        req = MethodRequest(url=j["s3_url"],
                            data=data,
                            headers={"Content-Type": ("multipart/form-data; boundary=%s"
                                                      % S3Multipart.boundary),
                                     "Content-Length": datalen
                                     }
                            )
        self.opener.open(req).read()
        return rv

if __name__ == "__main__":
    from optparse import OptionParser

    parser = OptionParser()
    parser.add_option("-r",
                      "--repo",
                      help="Github repository"
                      )
    parser.add_option("-u",
                      "--user",
                      help="User name"
                      )
    parser.add_option("-p",
                      "--password",
                      help="Password")

    opts, args = parser.parse_args()
    if not opts.repo or not opts.user or not opts.password:
        parser.error("Need to provide repo, user and password")

    d = Downloads(
                  repo=opts.repo,
                  user=opts.user,
                  password=opts.password,
                  debug=0
                  )
    print d.upload(args[0], replace=True)
