from commit import get_service_json
import jsonschema
import subprocess
import fnmatch

_action_schema = {
    'type': 'object',
    'properties': {
        'command': {
            'description': 'shell command to run',
            'type': 'string'
        },
        'not_after': {
            'description': 'don\'t run this after any of these actions',
            'type' : 'array',
            'items': {
                'type': 'string'
            },
            'uniqueItems': True
        }
    },
    'required': ['command']
}

_reaction_schema = {
    'type':'array',
    'items':{
        'type':'object',
        'properties':{
            'execute':{
                'description':'which action to execute',
                'type':'array',
                'items':{
                    'type':'string'
                },
                'minItems': 1,
                'uniqueItems':True
            },
            'when':{
                'type':'object',
                'properties':{
                    'command':{
                        'description':'command to run, use with exitcode',
                        'type':'string'
                    },
                    'exitcode':{
                        'description':'exit code to match',
                        'type':'integer'
                    },
                    'files':{
                        'description':'if any of these files were modified',
                        'type':'array',
                        'items':{
                            'type':'string'
                        }
                    }
                }
            }
        },
        'required': ['execute']
    }
}

def get_service_actions(service_dir, service_name, service_ver):
    """
    Gets the actions supported by a service

    Keyword arguments:
        service_dir -- top level service directory
        service_name -- name of service
        service_ver -- service version
    """
    action_desc = get_service_json(service_dir, service_name, service_ver, 'actions')

    result = {}
    for k,v in action_desc.items():
        if '.' in k:
            raise ValueError('Key {} in {} v{} is invalid, no dots allowed'.format(
                k, service_name, service_ver))
        jsonschema.validate(v, _action_schema)

        if 'not_after' in v:
            # Prepend service name and dots to any not_after items
            not_after = []
            for subitem in v['not_after']:
                if '.' not in subitem:
                    not_after.append(service_name + '.' + subitem)
                else:
                    not_after.append(subitem)

            v['not_after'] = not_after

        # Prepend dot for the action name always
        result[service_name + '.' + k] = v

    return result

def get_reactions(service_dir, service_name, service_ver):
    """
    Gets the reaction description from a service.

    Keyword arguments:
        service_dir -- top level service directory
        service_name -- name of service
        service_ver -- service version
    """
    reactions_desc = get_service_json(service_dir, service_name, service_ver, 'react')

    jsonschema.validate(reactions_desc, _reaction_schema)

    for reaction in reactions_desc:
        actions = []
        for action in reaction['execute']:
            if '.' not in action:
                actions.append(service_name + '.' + action)
            else:
                actions.append(action)

        reaction['execute'] = actions

    return reactions_desc


def _checkfiles(filepatterns, paths_changed):
    """
    Checks to see if any of the files changed match any of the file
    patterns given. File patterns implicitly start at the root of the
    deployment directory.

    Keyword arguments:
        filepatterns -- list of glob-style patterns
        paths_changed -- list of paths changed, each item is relative to the
            base deployment directory
    """
    for pattern in filepatterns:
        if fnmatch.filter(paths_changed, pattern):
            return True

    return False

def react(actions, reactions, paths_changed):
    """
    Performs actions based on reaction criteria. Each action is only performed
    once, and reactions are handled in order.

    Keyword arguments:
        actions -- map of action names to action descriptions
        reactions -- list of reactions to check for
        paths_changes -- list of files that were updated
    """
    done_actions = set()
    for reaction in reactions:
        if 'when' in reaction:
            when = reaction['when']
            if 'command' in when:
                command = when['command']
                exitcode = when['exitcode']
                ret = subprocess.call(command)
                if ret != exitcode:
                    continue
            elif 'files' in when:
                if not _checkfiles(when['files'], paths_changed):
                    continue #no files matched, skip this
            else:
                raise ValueError('When block with neither command nor files')

        # Run action
        for action in reaction['execute']:
            if action in actions:
                if action not in done_actions:
                    # Actions must be unique
                    not_after = set()
                    action_item = actions[action]
                    if 'not_after' in action_item:
                        not_after = set(action_item['not_after'])

                    if len(done_actions.intersection(not_after)) == 0:
                        # Let's do this
                        command = action_item['command']

                        try:
                            subprocess.check_call(command.split())
                            done_actions.add(action)
                        except subprocess.CalledProcessError as e:
                            print "Command {} errored with code {}".format(command, e.returncode)
                            raise e
            else:
                raise ValueError(
                        'Action {} from reaction {} not in action list'.format(
                            action, reaction))

