from github import Github
import requests
from nacl import encoding, public
# TODO: Reduce to just one encryption library :/
import codecs
from base64 import b64encode
import re
import json
from docassemble.base.util import log
from docassemble.base.core import DAObject

# reference:
# Mostly: https://pygithub.readthedocs.io/en/latest/introduction.html
# commit: https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html#github.Repository.Repository.create_git_commit
# branch? https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html#github.Repository.Repository.create_git_ref
# pull: https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html#github.Repository.Repository.create_pull
# repo key: https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html#github.Repository.Repository.get_keys


class TestInstaller(DAObject):
  def init( self, *pargs, **kwargs ):
    self.errors = []
    super().init(*pargs, **kwargs)
  
  def send_da_auth_secrets( self ):
    """Set the GitHub repo secrets the tests need to log into the da server and
    create projects to contain the interviews being tested. PyGithub does not yet handle secrets. See issue: https://github.com/PyGithub/PyGithub/issues/1373."""
    # Create org secret: https://docs.github.com/en/rest/reference/actions#create-or-update-an-organization-secret
    # Create repo secret: https://docs.github.com/en/rest/reference/actions#create-or-update-a-repository-secret
    self.set_github_auth()
    self.put_secret( secret_name='PLAYGROUND_EMAIL', secret_value=self.email )
    self.put_secret( secret_name='PLAYGROUND_PASSWORD', secret_value=self.password )
    self.set_da_server_info()
    self.put_secret( secret_name='PLAYGROUND_ID', secret_value=self.playground_id )
    return self
  
  def put_secret( self, secret_name='', secret_value='' ):
    """Add one secret to the GitHub repo."""
    # Everything should be authenticated by now.
    # Convert the message and key to Uint8Array's (Buffer implements that interface)
    encrypted_key = public.PublicKey( self.public_key.encode("utf-8"), encoding.Base64Encoder() )
    sealed_box = public.SealedBox( encrypted_key )
    encrypted = sealed_box.encrypt( secret_value.encode( "utf-8" ))  # Encrypt using LibSodium.
    base64_encrypted = b64encode( encrypted ).decode( "utf-8" )  # Base64 the encrypted secret
    #log( 'base64_encrypted', 'console' )
    #log( base64_encrypted, 'console' )
    
    secret_url = self.github_repo_base + "/actions/secrets/" + secret_name
    secret_payload = '{"encrypted_value":"' + base64_encrypted + '", "key_id":"' + self.key_id + '"}'
    secret_headers = {
      'Accept': "application/vnd.github.v3+json",
      'Authorization': self.basic_auth,
    }
    
    secret_response = requests.request( "PUT", secret_url, data=secret_payload, headers=secret_headers )
    #log( 'secret_response.text', 'console' )
    #log( secret_response.text, 'console' )
    
    # TODO: Check there was no error? Everything should be authorized by now.
    
    # Cannot get the value of the secret to see if we're setting it correctly
    # Can at least check that the secret exists
    response = requests.request( "GET", secret_url, data="", headers=secret_headers )
    #log( response.text, 'console' )
    
    return self

  def set_github_auth( self ):
    """Set values needed for GitHub authorization."""
    self.get_github_info_from_repo_url() # Gets self.repo_name
    
    # TODO:
    # Token doesn't work: github.GithubException.BadCredentialsException (401, 403)
    # Repo doesn't exist: github.GithubException.UnknownObjectException (404)
    
    # May not need owner name with this library
    try:
      self.github = Github( self.token )
      self.repo = self.github.get_user().get_repo( self.repo_name )
      self.owner_name = self.repo.owner.login
    except Exception as error:
      # TODO: Could this also mean the user is not a collaborator on the repo?
      # Try against https://github.com/google/model_search
      # TODO: Allow non-collaborator to make a fork and a pull request.
      if ( error.status == 401 ):
        error.data[ 'message' ] += '. It looks like we cannot find that personal access token. Try copying and pasting it again.'
      self.errors.append( error )
      log( error, 'console' )
      return self
    
    # TODO: Check user permissions: https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html#github.Repository.Repository.get_collaborator_permission
    self.user_name = self.github.get_user().login
    #self.repo.get_collaborator_permission( self.user_name )
    #if something:
    #  error.data[ 'message' ] += '. It looks like the ' + self.user_name + ' account does not have permission to edit this repository. Try to see if you can edit the code manually when signed in with that account. If that does not work, talk with your administrator. If that does work, file an issue with us.'
    #  return self
    
    # The below is only needed because PyGithub does not handle secrets
    # The value for the GitHub 'Authorization' key
    auth_bytes = codecs.encode(bytes( self.owner_name + ':' + self.token, 'utf8'), 'base64')
    self.basic_auth = 'Basic ' + auth_bytes.decode().strip()
    # The base url string needed for making requests to the repo.
    self.github_repo_base = "https://api.github.com/repos/" + self.owner_name + "/" + self.repo_name
    self.set_key_values()
    
    return self
  
  def get_github_info_from_repo_url( self ):
    """Use repo address to parse out owner name and repo name. Needs self.repo_url"""
    # Match either the actual URL or the clone HTTP or SSH URL
    matches = re.match(r"^.+github.com(?:\/|:)([^\/]*)\/([^\/.]*)(?:\..{3})?", self.repo_url)
    if matches:
      self.repo_name = matches.groups(1)[1]
    else:
      self.repo_name = None
      error = ErrorLikeObject( 'Cannot validate the GitHub URL "' + self.repo_url + '". If you are sure you have the whole correct URL the repository, please report a bug and include your interview URL in the report.' )
      self.errors.append( error )
      log( error, 'console' )
    return self
  
  def set_key_values( self ):
    """Gets and sets GitHub key id for the repo. Needed for auth to
    set secrets, etc. Needs set_github_auth()"""
    key_url = self.github_repo_base + "/actions/secrets/public-key"
    key_payload = ""
    key_headers = {
      'Accept': 'application/vnd.github.v3+json',
      'Authorization': self.basic_auth,
    }
    
    key_response = requests.request( 'GET', key_url, data=key_payload, headers=key_headers )
    key_json = json.loads( key_response.text )
    self.key_id = key_json[ 'key_id' ]
    self.public_key = key_json[ 'key' ]
    return self
    
  def set_da_server_info( self ):
    """Use the interview url to get the user's Playground id."""
    # Can probably do both in one match, but maybe we want to get granular with
    # our error messages...?
    server_match = re.match( r"^(http.+)\/interview\?i=docassemble\.playground(\d+).*$", self.playground_url )
    if server_match is None:
      self.server_url = None
      self.playground_id = None
      error = ErrorLikeObject( 'Cannot validate the interview URL "' + self.playground_url + '". If you are sure you have the whole URL of a running interview, please report a bug and include your interview URL in the report.' )
      self.errors.append( error )
      log( error, 'console' )
    else:
      # TODO: More fine-grained validation of this information
      self.server_url = server_match.group(1)
      self.playground_id = server_match.group(2)
    
    # TODO: Is it possible to try to log into their server to
    # make sure they've given the correct information?
    
    return self
  
  def create_branch( self ):
    """Create a new branch on the given repository. Make sure branch doesn't already exist."""
    # Get default branch
    repo = self.repo
    default_branch_name = repo.default_branch
    default_branch = repo.get_branch( default_branch_name )
    
    # Loop through branch names until one is available
    final_error = ErrorLikeObject( '' )
    branch_name_base = "automated_testing"
    branch_name = branch_name_base
    ref_path = "refs/heads/" + branch_name  # path of new branch
    count = 1
    max_count = 20
    while ( count < max_count ):
      try:
        response = repo.create_git_ref( ref_path, default_branch.commit.sha )
        break
      except Exception as error:  # github.GithubException.GithubException
        count += 1
        branch_name = branch_name_base + '_' + str( count )
        ref_path = "refs/heads/" + branch_name
        # Why does this make things get stuck on a previous page? (first page?)
        # Some kind of exception in here? Lets hope it doesn't occur at all.
        if count == max_count:
          # TODO: Tell the user to delete old branches
          final_error = error
          self.errors.append( error )
          
    # Check if the last error was 'branch already exists' error
    if len(self.errors) > 0 and not self.errors[ len(self.errors) - 1 ].status == 422:
      log( self.errors, 'console' )
    elif ( final_error.status == 422 ):
      final_error.data[ 'message' ] += '. It looks like all the possible branch names are taken. Please delete some of the branches that start with ' + branch_name_base + '.'
      log( final_error, 'console' )
    
    self.branch_name = branch_name
    return self
  
  def push_files( self ):
    ''' Commits and pushes all the needed files.'''
    # https://pygithub.readthedocs.io/en/latest/github_objects/Repository.html#github.Repository.Repository.create_file
    self.repo.create_file('.env_example', 'Add .env_example', self.env_example_str, branch=self.branch_name)  # 1
    self.repo.create_file('tests/features/example_test.feature', 'Add tests/features/example_test.feature', self.example_test_str, branch=self.branch_name)  # 2
    self.repo.create_file('.gitignore', 'Add .gitignore', self.gitignore_str, branch=self.branch_name)  # 3
    self.repo.create_file('package.json', 'Add package.json', self.package_json_str, branch=self.branch_name)  # 4
    self.repo.create_file('.github/workflow/run_form_tests.yml', 'Add r.github/workflow/run_form_tests.yml', self.run_interview_tests_str, branch=self.branch_name)  # 5
    
    return self

  def make_pull_request( self ):
    # https://pygithub.readthedocs.io/en/latest/examples/PullRequest.html
    # TODO: Check mergability of a PR
    base_name = self.repo.default_branch
    head_name = self.branch_name
    title = 'Update to automated tests'  # TODO: Add issue # if desired
    description = '''
Updates:
- [x] .env_example
- [x] tests/features/example_test.feature
- [x] .gitignore
- [x] package.json
- [x] .github/workflow/run_form_tests.yml
'''  # TODO: Add issue # if desired
    response = self.repo.create_pull(base=base_name, head=head_name, title=title, body=description)
    self.pull_url = response.url
    
    return self


class ErrorLikeObject():
  def __init__( self, message='' ):
    self.status = 0
    self.data = { 'message': message }