"""
filename: u_email.py
datetime: 2019-07-08
author: muumlover
"""
import base64
import logging
import smtplib
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import dns.resolver
from aiohttp.abc import Application


def setup_email(app: Application) -> None:
    if 'config' not in app:
        raise Exception('需要初始化配置参数')
    EmailSender.charset = app['config']['email']['charset']
    EmailSender.sender = app['config']['email']['sender']
    EmailSender.servers = app['config']['email']['servers']
    app['email'] = EmailSender


def rfc2047(s, charset='utf-8', language=None):
    """Encode string according to RFC 2231.
    """
    s = base64.b64encode(s.encode(charset)).decode()
    return "=?%s?b?%s?=" % (charset, s)


class EmailContext:
    subject = None
    message = None
    attach = None

    def __init__(self, subject):
        self.subject = subject
        pass


class EmailSender:
    charset = None
    sender = None

    @staticmethod
    async def _make_email(to_addrs, subject, mail_msg, attachs):
        logging.debug((to_addrs, subject, mail_msg, attachs))
        charset = EmailSender.charset
        if attachs is None:
            message = MIMEText(mail_msg, _subtype='html', _charset=charset)
        else:
            message = MIMEMultipart()
            msg_text = MIMEText(mail_msg, _subtype='html', _charset=charset)
            message.attach(msg_text)
            if isinstance(attachs, tuple):
                attachs = [attachs]
            for name, fp in attachs:
                attachment = MIMEApplication(fp.getvalue(), 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                # 纯英文可用，中文乱码
                # attachment['Content-Disposition'] = f'attachment; filename="{name}"'
                # 客户端兼容性不好，RFC2231 *= 格式
                # attachment.add_header('Content-Disposition', 'attachment', filename=(charset, '', name))
                # RFC2047 规范，使用广泛
                # filename = f'=?{charset}?B?{base64.b64encode(name.encode(charset)).decode()}?='
                attachment.add_header('Content-Disposition', 'attachment', filename=rfc2047(name, charset))
                message.attach(attachment)
        message['Subject'] = Header(subject, charset=charset).encode()
        message['From'] = f'{rfc2047("票券管理平台", charset)} <{EmailSender.sender}>'
        message['To'] = ';'.join([f'{rfc2047("平台用户", charset)} <{to_addr}>' for to_addr in to_addrs])

    @staticmethod
    async def _send_direct(message, to_addrs):
        to_domain_set = set([to_addr.split('@')[1] for to_addr in to_addrs])
        for to_domain in to_domain_set:
            send_addrs = [x for x in to_addrs if to_domain in x]
            try:
                with SmtpDirectServer(to_domain) as smtp_server:
                    send_errs = smtp_server.send_message(message, EmailSender.sender, send_addrs)
                    if not send_errs:
                        logging.debug(f'邮件投递到{to_domain}成功')
                    else:
                        logging.error(f'邮件投递到{to_domain}失败')
                        logging.error(send_errs)
            except dns.resolver.NoAnswer:
                logging.error(f'服务器 {to_domain} MX 记录解析失败')

    @staticmethod
    async def _send_proxy(message, to_addrs):
        for server in EmailSender.servers:
            try:
                logging.debug('使用邮件服务器：' + server['host'])
                with SmtpProxyServer(server['host'], 25, server['user'], server['pass']) as smtp_server:
                    send_errs = smtp_server.sendmail(EmailSender.sender, to_addrs, message)
                    if not send_errs:
                        logging.debug('邮件发送成功')
                        return
                    else:
                        logging.error('邮件发送失败')
                        logging.error(send_errs)
            except Exception as e:
                logging.exception(e)
        raise smtplib.SMTPDataError(-1, b'Unknown Error')

    @staticmethod
    async def send(to_addrs, subject, mail_msg, attachs=None):
        if isinstance(to_addrs, str):
            to_addrs = [to_addrs]
        logging.debug(('邮件收件人：', to_addrs))
        message = await EmailSender._make_email(to_addrs, subject, mail_msg, attachs)
        # with open('send_email.eml', 'wb') as fd:
        #     logging.debug('邮件已经保存到本地文件')
        #     fd.write(message.as_bytes())
        #     return
        try:
            await EmailSender._send_direct(message, to_addrs)
        except Exception as err:
            logging.error(f'邮件直接投递失败')
            logging.exception(err)
            try:
                await EmailSender._send_proxy(message, to_addrs)
            except Exception as err:
                logging.error(f'邮件中转投递失败')
                logging.exception(err)
                raise smtplib.SMTPDataError(-1, b'Unknown Error')


class SmtpDirectServer:
    def __init__(self, domain):
        mx = dns.resolver.query(domain, 'MX')
        server_addr = mx[0].exchange.to_text()
        logging.debug(f'目标邮件服务器：{server_addr}')
        _server = smtplib.SMTP(server_addr)
        self.server = _server

    def __enter__(self):
        return self.server

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.server.quit()


class SmtpProxyServer:
    def __init__(self, host, port, mail_user, mail_pass):
        _server = smtplib.SMTP(host, port)
        _server.login(mail_user, mail_pass)
        self.server = _server

    def __enter__(self):
        return self.server

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.server.quit()


if __name__ == '__main__':
    from sys import stdout

    logging.basicConfig(
        format='%(levelname)s: %(asctime)s [%(filename)s:%(lineno)d] %(message)s',
        level=logging.NOTSET,
        stream=stdout)

    import pathlib
    from config import load_config

    conf = load_config(str(pathlib.Path('..') / 'config' / 'polls.yaml'))
    EmailSender.charset = conf['email']['charset']
    EmailSender.servers = conf['email']['servers']

    import xlwt
    from io import BytesIO

    # 创建一个文件对象
    wb = xlwt.Workbook(encoding='utf-8')
    # 创建一个sheet对象
    sheet = wb.add_sheet('order-sheet')

    style_heading = xlwt.easyxf("""
                font:
                    name Arial,
                    colour_index white,
                    bold on,
                    height 0xA0;
                align:
                    wrap off,
                    vert center,
                    horiz center;
                pattern:
                    pattern solid,
                    fore-colour 0x19;
                borders:
                    left THIN,
                    right THIN,
                    top THIN,
                    bottom THIN;
                """)

    # 写入文件标题
    sheet.write(0, 0, '申请编号', style_heading)
    sheet.write(0, 1, '客户名称', style_heading)
    sheet.write(0, 2, '联系方式', style_heading)
    sheet.write(0, 3, '身份证号码', style_heading)
    sheet.write(0, 4, '办理日期', style_heading)
    sheet.write(0, 5, '处理人', style_heading)
    sheet.write(0, 6, '处理状态', style_heading)
    sheet.write(0, 7, '处理时间', style_heading)

    # 写出到IO
    output = BytesIO()
    wb.save(output)

    EmailSender.send(
        'wangsen@primeton.com', '数据导出报表',
        '您好：请在这里<a class="follow-nickName" href="https://me.csdn.net/offbeatmine" target="_blank">下载报表</a>',
        ('Download.xlsx', output))
    # EmailSender.send_attach(
    #     'wangsen@primeton.com', '数据导出报表',
    #     '您好：请在这里<a class="follow-nickName" href="https://me.csdn.net/offbeatmine" target="_blank">下载报表</a>')
