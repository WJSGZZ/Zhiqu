"""记录写作模型及实际渲染代码版本；未记录的历史写作模型不能推猜。"""
import hashlib
from pathlib import Path


def authoring_errors(case):
    authoring=case.get('authoring')
    if not isinstance(authoring,dict) or not isinstance(authoring.get('model'),str) or not authoring['model'].strip():
        return ['case.json authoring.model：缺写作模型名称与版本；历史模型未知时明确填写“未记录”']
    return []


def trace_metadata(case,renderer_files):
    errors=authoring_errors(case)
    if errors:raise ValueError('；'.join(errors))
    paths=[Path(path) for path in renderer_files]
    files={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    version=hashlib.sha256('\n'.join(name+':'+sha for name,sha in sorted(files.items())).encode()).hexdigest()
    return {'authoring':{'model':case['authoring']['model']},
            'renderer':{'version':'sha256:'+version,'files_sha256':files}}
