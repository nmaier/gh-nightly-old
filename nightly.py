import os, sys, re
import datetime
import hashlib

from ConfigParser import SafeConfigParser
from glob import glob
from io import BytesIO
from time import strftime
from xml.dom.minidom import parse as XML
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED


from path import path

from githubdownloads import Downloads as GHDownloads

class ZipOutFile(ZipFile):
    def __init__(self, zfile):
        ZipFile.__init__(self, zfile, "w", ZIP_DEFLATED)
    def __enter__(self):
        return self
    def __exit__(self, type, value, traceback):
        self.close()

KEYS = ["user", "pass", "repo", "extension", "dirname", "hashalgo"]
CKEYS = ["altupdateurl", "altupdatepath", "versionextra"]

def main():
    nightlydir = path(__file__).dirname()

    parser = optparse.OptionParser()
    parser.add_option("-u", "--user")
    parser.add_option("-p", "--pass")
    parser.add_option("-r", "--repo")
    parser.add_option("-e", "--extension")
    parser.add_option("-d", "--dirname")
    parser.add_option("-v", "--versionextra")
    parser.add_option("--hashalgo")
    parser.add_option("--altupdateurl")
    parser.add_option("--altupdatepath")

    options, args = parser.parse_args()

    # load config
    cf = SafeConfigParser()
    if args:
        cf.read(path(args[0]))
    else:
        cf.read(nightlydir / "config.ini")
    config = dict()
    for k in KEYS:
        try:
            config[k] = getattr(options, k) or cf.get("github", k)
        except:
            config[k] = None

        if not config[k]:
            raise Exception("Not all required config keys specified: " + k)
    for k in CKEYS:
        try:
            config[k] = getattr(options, k) or cf.get("github", k)
        except:
            config[k] = None

    with open(nightlydir / "update-nightly.rdf") as domp:
        updaterdf = XML(domp)

    version = None
    out = BytesIO()
    with ZipOutFile(out) as zp:
        dirname = path(config["dirname"]).expanduser()
        for f in dirname.walk():
            if f.isdir() or f.basename() == "install.rdf":
                continue
            zf = f[len(dirname) + 1:]
            if zf.endswith(".png"):
                zp.write(f, zf, compress_type=ZIP_STORED)
            else:
                zp.write(f, zf)

        with open(dirname / "install.rdf") as domp:
            dom = XML(domp)

        # Set up update.rdf extid
        un = updaterdf.getElementsByTagName("RDF:Description")[0]
        vn = dom.getElementsByTagName("em:id")[0]
        un.setAttribute("about",
                        ("urn:mozilla:extension:%s" %
                         vn.firstChild.data
                         )
                        )

        # Set up the version
        vn = dom.getElementsByTagName("em:version")[0].firstChild
        version = vn.data + "." + strftime("%Y%m%d.%H%M")
        if config["versionextra"]:
            version += "." + config["versionextra"]
        vn.data = version

        # Set up update.rdf version
        un = updaterdf.getElementsByTagName("em:version")[0]
        un.firstChild.data = version

        # Set up update.rdf target application
        un = un.parentNode
        for n in dom.getElementsByTagName("em:targetApplication"):
            nn = n.cloneNode(True)
            for nd in nn.getElementsByTagName("Description"):
                nd.tagName = "RDF:Description"
            un.appendChild(nn)

        # Get the update info in order
        for n in dom.getElementsByTagName("em:updateKey"):
            n.parentNode.removeChild(n)
        try:
            n = dom.getElementsByTagName("em:updateURL")[0]
            while n.firstChild:
                n.removeChild(n.firstChild)
        except:
            n = dom.createElement("em:updateURL")
            un.appendChild(n)
        update_url = (config["altupdateurl"]
                      or"https://github.com/downloads/%s/update-nightly.rdf" % config["repo"]
                      )
        n.appendChild(dom.createTextNode(update_url))

        # write install.rdf
        zp.writestr("install.rdf", dom.toxml(encoding="utf-8"))

    out.seek(0)
    outfile = "%s-nightly-%s.xpi" % (config["extension"], version)

    downloads = GHDownloads(repo=config["repo"],
                            user=config["user"],
                            password=config["pass"]
                            )

    # clean up
    cutoff = datetime.date.today() - datetime.timedelta(365/12)
    cutoff = cutoff.strftime("%Y%m%d.%H%M")
    for df in downloads.list():
        m = re.search(r"nightly.*\.(\d{8})", df.name)
        if not m or m.group(1) > cutoff:
            continue
        downloads.delete(df.id)

    # upload the new file
    upload = downloads.upload(
                              out,
                              outfile,
                              mime="application/x-xpinstall",
                              replace=True)

    # finish update.rdf
    hash = updaterdf.createElement("em:updateHash")
    sum = hashlib.new(config["hashalgo"])
    sum.update(out.getvalue())
    sum = "%s:%s" % (config["hashalgo"],
                     sum.hexdigest()
                     )
    hash.appendChild(updaterdf.createTextNode(sum))

    link = updaterdf.createElement("em:updateLink")
    link.appendChild(updaterdf.createTextNode(upload.download_url))

    for nt in un.getElementsByTagName("em:targetApplication"):
        for n in nt.getElementsByTagName("RDF:Description"):
            n.appendChild(hash.cloneNode(True))
            n.appendChild(link.cloneNode(True))

    updaterdf = updaterdf.toxml(encoding="utf-8")

    # put the update.rdf
    if not "altupdatepath" in config:
        downloads.upload(BytesIO(updaterdf),
                         "update-nightly.rdf",
                         replace=True
                         )
    else:
        with open(path(config["altupdatepath"]).expanduser(), "wb") as up:
            up.write(updaterdf)

    return 0

if __name__ == "__main__":
    import optparse
    sys.exit(main())

