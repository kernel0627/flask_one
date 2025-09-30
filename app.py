from flask import Flask , Response , jsonify  , render_template
import requests , io , tarfile , json , mimetypes , os
import nodesemver as semver
from flask_caching import Cache

app = Flask(__name__)

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/'
}

config = {
    "CACHE_TYPE" : "FileSystemCache",
    "CACHE_DIR" : os.path.join(os.path.abspath(os.path.dirname(__file__)),"cache"),
    "CACHE_DEFAULT_TIMEOUT": 3600
}
app.config.from_mapping(config)
cache = Cache(app)

# https://registry.npmjs.org/alpha

def get_full_version(name):
    registry = os.environ.get('REGISTRY' , 'https://registry.npmjs.org')
    url = f'{registry}/{name}'
    response = requests.get(url , headers=headers)
    if response.status_code != 200:
        return None
    data = response.json()
    versions = list(data.get('versions', {}).keys())
    return versions ,data

def  handle_version(name, version):
    print('handle')
    versions , data = get_full_version(name)
    if not data :
        print('no data')
        return version
    if version in data.get('dist-tags' , {}):
        resolved = data['dist-tags'][version]
        print(resolved)
        return resolved
    all_versions = data.get('versions' , {}).keys()
    # print(all_versions)



    # # 我这儿semver没有satisfies我得自己造个轮子
    # 然后我发现很搞笑的是node-semver就有，根本不需要，笑死
    # matching_versions = []
    # for v in all_versions:
    #     # print(version)
    #     try:
    #         parsed_version = semver.VersionInfo.parse(v)
    #         print(parsed_version)
    #         if not parsed_version.prerelease:
    #             if semver.satisfies(v, version):
    #                 matching_versions.append(v)
    #     except ValueError:
    #         continue
    #
    # print(matching_versions)
    # if matching_versions:
    #         print('matching')
    #         best_version = max(matching_versions)
    #         return best_version

    best_version = semver.max_satisfying(all_versions, version, loose=True)

    if best_version:
        print(best_version)
        return best_version

    print('no match')
    return version

def parse_path(url):
    parts = url.split('/' , 1)
    if len(parts) == 2:
        info_string = parts[0]
        file_path = parts[1]
    else :
        info_string = parts[0]
        file_path = ''

    info_parts = info_string.split('@')
    if len(info_parts) == 2:
        name = info_parts[0]
        version = info_parts[1]
    else:
        name = info_parts[0]
        version = 'latest'

    # 判断是否需要处理版本号
    if  version in ['latest' , 'next' , 'beta' , 'alpha'] or version.startswith(('^' , '~' , '>' , '<' , '=')) or ' ' in version or '*' in version:
        version = handle_version(name, version)
    print(name , version , file_path)
    return name , version , file_path

@cache.memoize(timeout=3600)
def get_package(name , version ):
    registry = os.environ.get('REGISTRY' , 'https://registry.npmjs.org')

    url = f'{registry}/{name}'
    if version:
        url += f'/{version}'
    response = requests.get(url , headers=headers)
    if response.status_code != 200:
        return jsonify({'msg':'Package not found'}) , 404
    return response.json()

@cache.memoize(timeout=84600)
def download_package(tarball_url):
    try :
        response = requests.get(tarball_url , headers=headers)
        response.raise_for_status()
        return response.content
    except requests.RequestException as e:
        print(e)
        return None

def download_unpack_package(tarball_url):
    response = download_package(tarball_url)
    if not response:
        return None
    file =  io.BytesIO(response)
    return tarfile.open(fileobj=file , mode='r:gz')

def get_url(data):
    url = ''
    with open('shit.txt' , 'w' , encoding='utf-8') as s :
        for k,v in data.items():
            s.write(f'{{  {k} : {v} }}\n')
    if not data:
        return None
    if 'exports' in data :
        if '.'  in data['exports'] and isinstance(data['exports']['.'], dict) :

            if 'default' in data['exports']['.']:
                print('shit')
                url = data['exports']['.']['default']
            elif data['main'] :
                print('bullshit')
                url = data['main']
            else :
                print('default')
                url = 'index.js'
        else:
            url = data['exports']['.']
    elif 'main' in data and  data['main'] :
        print('bullshit')
        url = data['main']
    else :
        url = 'index.js'
    return url.lstrip('./')

def file_request(tar , path  , name , version ):
    # print(path)

    if not 'package/' in path :
        path = 'package/' + path
        # print(path)
    # print('file')
    # print(path)
    cached_key = f"{name}@{version}::{path}"
    file_content = cache.get(cached_key)
    if file_content :
        mime_type, _ = mimetypes.guess_type(path)
        if mime_type:
            return Response(file_content, mimetype=mime_type, status=200)
        return Response(file_content, mimetype='text/plain', status=200)
    files = tar.getnames()
    # print(files)
    if not path in files :
        print('not file')
        return jsonify({'msg':'No Found1'} ), 404
    file = tar.extractfile(path)
    if file:
        content = file.read()
        # no need for decoding as we send to the web , it could it as we give the mimetype
        cache.set(cached_key , content , timeout=3600)
        mime_type, _ = mimetypes.guess_type(path)
        if  mime_type:
            return Response(content, mimetype=mime_type, status=200)
        return Response(content , mimetype='text/plain' , status=200)
    else:
        print(f" {path} 未找到")
        return jsonify({'msg':'No Found2'}) , 404

# entry file 要得到
def entry_file_request(tar  , name , version ):
    print('entry')
    path = 'package/package.json'
    file = tar.extractfile(path)
    content = file.read().decode('utf-8')
    data = json.loads(content)
    path = get_url(data)
    print(path)
    return file_request(tar , path , name , version)

def directory_request(tar , name , version ):
    print('directory')
    # lists = tar.getnames()
    lists = []
    for member in tar.getmembers():
        if member.isfile():
            clean_path = member.name
            file_name = os.path.basename(clean_path)
            lists.append({
                'path': clean_path,
                'name': file_name,
                'size': member.size
            })
    lists.sort(key=lambda x : x['path'])
    # context = {
    #     'name' : name ,
    #     'lists' : lists
    # }
    # print(lists)
    return render_template('lists.html' ,version = version ,  name=name, lists=lists)
    # if mime_type:
    #     return Response('\n'.join(lists), mimetype=mime_type, status=200)
    # return Response('\n'.join(lists) , mimetype='text/plain' , status=200)


@app.route('/')
def hello_world():  # put application's code here
    return jsonify({'msg':'Hello World!'}) , 201


@app.route('/<path:url>' , methods=['GET'])
def proxy(url):
    name, version, file_path = parse_path(url)
    print(version)
    data = get_package(name , version)
    if not data :
        return 'Package not found' , 404
    # if not isinstance(data, dict):
    #     return Response(data, mimetype='text/plain' , status=200)
    print(type(data['dist']))
    if (type(data['dist']) == tuple) :
        return Response('Package not found', 404)
    dist = data.get('dist' , {})
    if not dist :
        return Response('Package not found', 404)
    tarball_url = dist['tarball']
    tarball_data = download_unpack_package(tarball_url)
    if not tarball_data:
        return Response('Failed to download package', 500)

    # 2.b
    if url.endswith('/'):
        name = name + '@' + version
        return directory_request(tarball_data, name , version)
    # 2.a
    elif not file_path:
        return entry_file_request(tarball_data , name , version )
    # 2.c
    else :
        return file_request(tarball_data , file_path , name , version )
#
# @app.route('/<path:url>/1' , methods=['GET'])
# def test(url):
#     return render_template('layout.html' , url =url)

if __name__ == '__main__':
    app.run(debug=True)

    # redis & zip & about ram release
    # & special release kind like /vue/ and /vue@^3.2.0/ to tackle
    #change
    # flask_caching instead redis no need for ram release
    # totally rebuild for the version logic
    # must get
