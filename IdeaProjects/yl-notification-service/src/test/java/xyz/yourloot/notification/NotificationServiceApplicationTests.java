package xyz.yourloot.notification;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;

@Import(ContainerTest.class)
@SpringBootTest
public class NotificationServiceApplicationTests {

    @Test
    public void contextLoads() {
    }

}
