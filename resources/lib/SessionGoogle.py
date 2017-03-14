# code from: http://stackoverflow.com/questions/6754709/logging-in-to-google-using-python

class SessionGoogle:
    def __init__(self, login, pwd):
        import requests
        from bs4 import BeautifulSoup
        self.ses = requests.session()
        url_login = "https://accounts.google.com/ServiceLogin"
        url_auth = "https://accounts.google.com/ServiceLoginAuth"
        login_html = self.ses.get(url_login)
        soup_login = BeautifulSoup(login_html.content, 'html.parser').find('form').find_all('input')
        my_dict = {}
        for u in soup_login:
            if u.has_attr('value'):
                my_dict[u['name']] = u['value']
        # override the inputs without login and pwd:
        my_dict['Email'] = login
        my_dict['Passwd'] = pwd
        self.ses.post(url_auth, data=my_dict)

    def get(self, URL):
        return self.ses.get(URL).text

